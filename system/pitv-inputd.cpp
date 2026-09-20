// PiTV TV Shell input daemon.
//
// One persistent libCEC owner for the entire appliance lifetime.
// Input arrives from libCEC callbacks; PiTV/Kodi/Android routing happens above
// this process. CEC output commands use the same connection so no second
// cec-ctl/libCEC process races for /dev/cec*.
//
// Protocol on /run/pitv/inputd.sock:
//   client -> "SUBSCRIBE\n"
//   daemon -> "STATE\tconnected|disconnected\t<adapter>\n"
//   daemon -> "KEY\t<cec_user_control_code>\t<duration_ms>\n"
//   daemon -> "SOURCE\t<logical_address>\t0|1\n"
//   client -> "CMD\tSTATUS|ACTIVE|POWER_ON|STANDBY|VOLUP|VOLDOWN|MUTE\n"
//   daemon -> "ACK\t<command>\t0|1\t<message>\n"

#include <libcec/cec.h>
#include <libcec/cecc.h>

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <deque>
#include <iostream>
#include <mutex>
#include <poll.h>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

using namespace CEC;

namespace {

constexpr const char* kSocketPath = "/run/pitv/inputd.sock";
constexpr int kPollMs = 100;
constexpr int kOpenTimeoutMs = 5000;
constexpr auto kReconnectDelay = std::chrono::milliseconds(800);

std::atomic<bool> g_stop{false};

void signal_handler(int) {
  g_stop.store(true);
}

std::string clean_field(std::string value) {
  for (char& c : value) {
    if (c == '\t' || c == '\n' || c == '\r')
      c = ' ';
  }
  return value;
}

bool send_all(int fd, const std::string& data) {
  size_t sent = 0;
  while (sent < data.size()) {
    const ssize_t n = ::send(fd, data.data() + sent, data.size() - sent,
                             MSG_NOSIGNAL);
    if (n > 0) {
      sent += static_cast<size_t>(n);
      continue;
    }
    if (n < 0 && errno == EINTR)
      continue;
    return false;
  }
  return true;
}

struct Client {
  int fd{-1};
  bool subscriber{false};
  std::string buffer;
};

class InputDaemon {
 public:
  InputDaemon() {
    config_.Clear();
    callbacks_.Clear();

    std::snprintf(config_.strDeviceName, sizeof(config_.strDeviceName), "%s",
                  "PiTV");
    config_.clientVersion = LIBCEC_VERSION_CURRENT;
    config_.bActivateSource = 0;
    config_.bPowerOffOnStandby = 0;
    config_.bMonitorOnly = 0;
    config_.comboKey = CEC_USER_CONTROL_CODE_UNKNOWN;
    config_.iComboKeyTimeoutMs = 0;

    // Let the TV send its native repeats. libCEC still owns press/release,
    // held-button timeout and vendor quirks, but duration==0 remains a real
    // press/repeat and duration>0 remains the matching release. This is ideal
    // for a TV-shell input router and preserves long-Back semantics.
    config_.iButtonRepeatRateMs = 0;
    config_.iDoubleTapTimeoutMs = 0;
    config_.deviceTypes.Clear();
    config_.deviceTypes.Add(CEC_DEVICE_TYPE_PLAYBACK_DEVICE);
    config_.wakeDevices.Clear();
    config_.powerOffDevices.Clear();

    callbacks_.keyPress = &InputDaemon::key_callback;
    callbacks_.alert = &InputDaemon::alert_callback;
    callbacks_.sourceActivated = &InputDaemon::source_callback;
    config_.callbackParam = this;
    config_.callbacks = &callbacks_;
  }

  ~InputDaemon() {
    close_cec();
    close_socket();
  }

  bool initialise() {
    connection_ = libcec_initialise(&config_);
    if (!connection_) {
      std::cerr << "pitv-inputd: libcec_initialise failed\n";
      return false;
    }
    libcec_init_video_standalone(connection_);
    const char* info = libcec_get_lib_info(connection_);
    std::cerr << "pitv-inputd: "
              << (info ? clean_field(info) : std::string("libCEC"))
              << "\n";
    return create_socket();
  }

  int run() {
    auto next_open = std::chrono::steady_clock::now();

    while (!g_stop.load()) {
      const auto now = std::chrono::steady_clock::now();

      if (reconnect_requested_.exchange(false)) {
        close_adapter_only();
        next_open = now + kReconnectDelay;
      }

      if (!connected_.load() && now >= next_open) {
        if (!open_adapter())
          next_open = now + std::chrono::seconds(2);
      }

      poll_once();
      flush_events();
    }
    return 0;
  }

 private:
  static void CEC_CDECL key_callback(void* param, const cec_keypress* key) {
    if (!param || !key)
      return;
    static_cast<InputDaemon*>(param)->on_key(*key);
  }

  static void CEC_CDECL alert_callback(void* param,
                                      const libcec_alert alert,
                                      const libcec_parameter) {
    if (!param)
      return;
    static_cast<InputDaemon*>(param)->on_alert(alert);
  }

  static void CEC_CDECL source_callback(void* param,
                                       const cec_logical_address address,
                                       const uint8_t activated) {
    if (!param)
      return;
    static_cast<InputDaemon*>(param)->enqueue(
        "SOURCE\t" + std::to_string(static_cast<int>(address)) + "\t" +
        (activated ? "1\n" : "0\n"));
  }

  void on_key(const cec_keypress& key) {
    enqueue("KEY\t" + std::to_string(static_cast<int>(key.keycode)) + "\t" +
            std::to_string(key.duration) + "\n");
  }

  void on_alert(libcec_alert alert) {
    enqueue("ALERT\t" + std::to_string(static_cast<int>(alert)) + "\n");
    if (alert == CEC_ALERT_CONNECTION_LOST ||
        alert == CEC_ALERT_PERMISSION_ERROR ||
        alert == CEC_ALERT_PORT_BUSY) {
      connected_.store(false);
      enqueue_state(false, "");
      reconnect_requested_.store(true);
    }
  }

  void enqueue(std::string message) {
    std::lock_guard<std::mutex> lock(events_mutex_);
    if (events_.size() >= 256)
      events_.pop_front();
    events_.push_back(std::move(message));
  }

  void enqueue_state(bool connected, const std::string& adapter) {
    enqueue("STATE\t" + std::string(connected ? "connected" : "disconnected") +
            "\t" + clean_field(adapter) + "\n");
  }

  bool create_socket() {
    ::unlink(kSocketPath);

    listen_fd_ = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (listen_fd_ < 0) {
      std::cerr << "pitv-inputd: socket failed: " << std::strerror(errno)
                << "\n";
      return false;
    }

    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", kSocketPath);
    if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) <
        0) {
      std::cerr << "pitv-inputd: bind failed: " << std::strerror(errno)
                << "\n";
      return false;
    }
    ::chmod(kSocketPath, 0660);
    if (::listen(listen_fd_, 8) < 0) {
      std::cerr << "pitv-inputd: listen failed: " << std::strerror(errno)
                << "\n";
      return false;
    }
    set_nonblock(listen_fd_);
    return true;
  }

  void close_socket() {
    for (auto& client : clients_) {
      if (client.fd >= 0)
        ::close(client.fd);
    }
    clients_.clear();
    if (listen_fd_ >= 0) {
      ::close(listen_fd_);
      listen_fd_ = -1;
    }
    ::unlink(kSocketPath);
  }

  static void set_nonblock(int fd) {
    const int flags = ::fcntl(fd, F_GETFL, 0);
    if (flags >= 0)
      ::fcntl(fd, F_SETFL, flags | O_NONBLOCK);
  }

  bool open_adapter() {
    if (!connection_)
      return false;

    cec_adapter_descriptor adapters[16]{};
    int8_t count = libcec_detect_adapters(connection_, adapters, 16, nullptr, 0);

    std::vector<int> order;
    for (int i = 0; i < count; ++i)
      order.push_back(i);

    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
      auto score = [&](int i) {
        int value = 0;
        if (adapters[i].adapterType == ADAPTERTYPE_LINUX)
          value += 100;
        const std::string comm = adapters[i].strComName;
        const std::string path = adapters[i].strComPath;
        if (comm.find("/dev/cec") != std::string::npos ||
            path.find("/dev/cec") != std::string::npos)
          value += 50;
        if (adapters[i].iPhysicalAddress != 0x0000 &&
            adapters[i].iPhysicalAddress != 0xffff)
          value += 20;
        return value;
      };
      return score(a) > score(b);
    });

    for (const int idx : order) {
      const char* candidate = adapters[idx].strComName[0]
                                  ? adapters[idx].strComName
                                  : adapters[idx].strComPath;
      if (!candidate || !candidate[0])
        continue;
      if (libcec_open(connection_, candidate, kOpenTimeoutMs)) {
        adapter_name_ = candidate;
        connected_.store(true);
        std::cerr << "pitv-inputd: connected " << adapter_name_ << "\n";
        enqueue_state(true, adapter_name_);
        return true;
      }
    }

    // libCEC also supports nullptr = first usable adapter. Keep this as a
    // compatibility path for distro builds that do not return descriptors.
    if (libcec_open(connection_, nullptr, kOpenTimeoutMs)) {
      adapter_name_ = "auto";
      connected_.store(true);
      std::cerr << "pitv-inputd: connected (auto)\n";
      enqueue_state(true, adapter_name_);
      return true;
    }

    connected_.store(false);
    adapter_name_.clear();
    enqueue_state(false, "");
    std::cerr << "pitv-inputd: no usable CEC adapter, retrying\n";
    return false;
  }

  void close_adapter_only() {
    if (!connection_)
      return;
    if (connected_.exchange(false)) {
      libcec_close(connection_);
      std::cerr << "pitv-inputd: CEC connection closed for reconnect\n";
    } else {
      // Close is safe even after a connection-lost alert and makes the next
      // open re-run adapter detection/address allocation.
      libcec_close(connection_);
    }
    adapter_name_.clear();
  }

  void close_cec() {
    if (!connection_)
      return;
    libcec_close(connection_);
    libcec_destroy(connection_);
    connection_ = nullptr;
    connected_.store(false);
  }

  void poll_once() {
    std::vector<pollfd> pfds;
    pfds.reserve(clients_.size() + 1);
    pfds.push_back({listen_fd_, POLLIN, 0});
    for (const auto& client : clients_)
      pfds.push_back({client.fd, POLLIN | POLLHUP | POLLERR, 0});

    const int rc = ::poll(pfds.data(), pfds.size(), kPollMs);
    if (rc < 0) {
      if (errno != EINTR)
        std::cerr << "pitv-inputd: poll failed: " << std::strerror(errno)
                  << "\n";
      return;
    }

    if (pfds[0].revents & POLLIN)
      accept_clients();

    for (size_t i = clients_.size(); i-- > 0;) {
      const short events = pfds[i + 1].revents;
      if (events & (POLLHUP | POLLERR | POLLNVAL)) {
        remove_client(i);
        continue;
      }
      if (events & POLLIN)
        read_client(i);
    }
  }

  void accept_clients() {
    while (true) {
      int fd = ::accept4(listen_fd_, nullptr, nullptr,
                         SOCK_CLOEXEC | SOCK_NONBLOCK);
      if (fd < 0) {
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
          std::cerr << "pitv-inputd: accept failed: " << std::strerror(errno)
                    << "\n";
        return;
      }
      clients_.push_back({fd, false, {}});
    }
  }

  void remove_client(size_t index) {
    if (index >= clients_.size())
      return;
    ::close(clients_[index].fd);
    clients_.erase(clients_.begin() + static_cast<long>(index));
  }

  void read_client(size_t index) {
    if (index >= clients_.size())
      return;

    char buf[512];
    while (true) {
      const ssize_t n = ::recv(clients_[index].fd, buf, sizeof(buf), 0);
      if (n > 0) {
        clients_[index].buffer.append(buf, static_cast<size_t>(n));
        if (clients_[index].buffer.size() > 4096) {
          remove_client(index);
          return;
        }
        continue;
      }
      if (n == 0) {
        remove_client(index);
        return;
      }
      if (errno == EAGAIN || errno == EWOULDBLOCK)
        break;
      if (errno == EINTR)
        continue;
      remove_client(index);
      return;
    }

    if (index >= clients_.size())
      return;

    while (true) {
      const size_t pos = clients_[index].buffer.find('\n');
      if (pos == std::string::npos)
        break;
      std::string line = clients_[index].buffer.substr(0, pos);
      clients_[index].buffer.erase(0, pos + 1);
      if (!line.empty() && line.back() == '\r')
        line.pop_back();
      handle_line(index, line);
      if (index >= clients_.size())
        return;
    }
  }

  void handle_line(size_t index, const std::string& line) {
    if (index >= clients_.size())
      return;

    if (line == "SUBSCRIBE") {
      clients_[index].subscriber = true;
      send_all(clients_[index].fd,
               "STATE\t" +
                   std::string(connected_.load() ? "connected" : "disconnected") +
                   "\t" + clean_field(adapter_name_) + "\n");
      return;
    }

    constexpr const char* prefix = "CMD\t";
    if (line.rfind(prefix, 0) != 0)
      return;

    const std::string command = line.substr(std::strlen(prefix));
    std::string message;
    const bool ok = execute_command(command, message);
    const std::string reply =
        "ACK\t" + clean_field(command) + "\t" + (ok ? "1" : "0") + "\t" +
        clean_field(message) + "\n";
    send_all(clients_[index].fd, reply);
  }

  bool execute_command(const std::string& command, std::string& message) {
    if (command == "STATUS") {
      message = connected_.load() ? adapter_name_ : "disconnected";
      return connected_.load();
    }
    if (!connected_.load() || !connection_) {
      message = "CEC disconnected";
      return false;
    }

    int rc = 0;
    if (command == "ACTIVE") {
      rc = libcec_set_active_source(connection_,
                                    CEC_DEVICE_TYPE_PLAYBACK_DEVICE);
    } else if (command == "POWER_ON") {
      rc = libcec_power_on_devices(connection_, CECDEVICE_TV);
    } else if (command == "STANDBY") {
      rc = libcec_standby_devices(connection_, CECDEVICE_TV);
    } else if (command == "VOLUP") {
      rc = libcec_volume_up(connection_, 1);
    } else if (command == "VOLDOWN") {
      rc = libcec_volume_down(connection_, 1);
    } else if (command == "MUTE") {
#if CEC_LIB_VERSION_MAJOR >= 5
      rc = libcec_mute_audio(connection_, 1);
#else
      rc = libcec_send_keypress(connection_, CECDEVICE_AUDIOSYSTEM,
                                CEC_USER_CONTROL_CODE_MUTE, 1);
      if (rc)
        rc = libcec_send_key_release(connection_, CECDEVICE_AUDIOSYSTEM, 1);
#endif
    } else if (command == "RECONNECT") {
      reconnect_requested_.store(true);
      message = "reconnect scheduled";
      return true;
    } else {
      message = "unsupported command";
      return false;
    }

    message = rc ? "ok" : "libCEC command failed";
    return rc != 0;
  }

  void flush_events() {
    std::deque<std::string> pending;
    {
      std::lock_guard<std::mutex> lock(events_mutex_);
      pending.swap(events_);
    }
    if (pending.empty())
      return;

    for (const std::string& event : pending) {
      for (size_t i = clients_.size(); i-- > 0;) {
        if (!clients_[i].subscriber)
          continue;
        if (!send_all(clients_[i].fd, event))
          remove_client(i);
      }
    }
  }

  libcec_configuration config_;
  ICECCallbacks callbacks_;
  libcec_connection_t connection_{nullptr};

  std::atomic<bool> connected_{false};
  std::atomic<bool> reconnect_requested_{false};
  std::string adapter_name_;

  int listen_fd_{-1};
  std::vector<Client> clients_;

  std::mutex events_mutex_;
  std::deque<std::string> events_;
};

}  // namespace

int main() {
  std::signal(SIGINT, signal_handler);
  std::signal(SIGTERM, signal_handler);
  std::signal(SIGHUP, signal_handler);
  std::signal(SIGPIPE, SIG_IGN);

  InputDaemon daemon;
  if (!daemon.initialise())
    return 1;
  return daemon.run();
}
