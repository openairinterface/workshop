// SPDX-License-Identifier: Apache-2.0
//
// Incumbent injector for the OAI RF simulator.
//
// Connects to the gNB's RF simulator server as one more client and sends it
// the uplink signal of one or more "incumbents" (tones, sweeps, hopping and
// duty-cycled signals) plus wideband Gaussian noise. The RF simulator sums
// every client's samples, so the gNB receives the UE and the incumbents together.
//
// Wire format (radio/rfsimulator/simulator.cpp of the OAI tree):
//   header  : u32 size, u32 nbAnt, u64 timestamp, u32 option_value, u32 option_flag
//   gains   : nbAnt x float32 (dB)
//   samples : nbAnt x size x {int16 I, int16 Q}
// The gNB is lock-stepped with its clients, so for every block it sends we
// answer with one block that has the same timestamp and size.
//
// Every waveform is a pure function of the sample timestamp, so a run is
// repeatable. The scenario is described in a JSON file, see ../../scenarios/.

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <string>
#include <thread>
#include <vector>

#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace {

struct BlockHeader {
  uint32_t size;
  uint32_t nbAnt;
  uint64_t timestamp;
  uint32_t option_value;
  uint32_t option_flag;
};
static_assert(sizeof(BlockHeader) == 24, "rfsim header layout changed");

struct Cell {
  double sample_rate = 61.44e6;
  int num_prbs = 106;
  double scs_hz = 30e3;
  // Baseband frequency (Hz, relative to the carrier centre) of a position given in PRB units.
  double freq_of_prb_pos(double x) const { return (x - num_prbs / 2.0) * 12.0 * scs_hz; }
};

uint64_t splitmix64(uint64_t x)
{
  x += 0x9e3779b97f4a7c15ULL;
  x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
  x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
  return x ^ (x >> 31);
}

constexpr int kTableBits = 14;
constexpr int kTableSize = 1 << kTableBits;
float g_cos[kTableSize], g_sin[kTableSize];
constexpr int kGaussSize = 1 << 16;
float g_gauss[kGaussSize];

void init_tables()
{
  for (int i = 0; i < kTableSize; i++) {
    double a = 2.0 * M_PI * i / kTableSize;
    g_cos[i] = (float)std::cos(a);
    g_sin[i] = (float)std::sin(a);
  }
  uint64_t s = 12345;
  for (int i = 0; i < kGaussSize; i += 2) {
    double u1 = ((splitmix64(s++) >> 11) + 1.0) / 9007199254740993.0;
    double u2 = (splitmix64(s++) >> 11) / 9007199254740992.0;
    double r = std::sqrt(-2.0 * std::log(u1));
    g_gauss[i] = (float)(r * std::cos(2.0 * M_PI * u2));
    g_gauss[i + 1] = (float)(r * std::sin(2.0 * M_PI * u2));
  }
}

double dbfs_to_amp(double dbfs) { return 32767.0 * std::pow(10.0, dbfs / 20.0); }

struct Component {
  std::string id;
  std::string shape = "tone"; // tone | sweep
  double start_s = 0, stop_s = 1e18;
  double amp = 0; // peak, int16 counts
  double amp_dbfs = 0;
  std::vector<double> positions; // lowest PRB (sweep) or PRB position of the tone; more than one when hopping
  double width_prb = 1;          // sweep width in PRBs
  double sweep_period_us = 50;
  double hop_dwell_s = 0;
  uint64_t hop_seed = 1;
  bool duty = false;
  double duty_period_s = 0, duty_on_s = 0, duty_offset_s = 0;
  double phase0 = 0; // initial phase in cycles
  double offset_prb = 0; // tone offset from the PRB centre, in PRBs

  // derived, in samples
  uint64_t start_n = 0, stop_n = UINT64_MAX, dwell_n = 0, duty_period_n = 0, duty_on_n = 0, duty_off_n = 0;
  uint64_t sweep_n = 1;
  mutable uint64_t hop_h = 0; // hop sequence cache
  mutable int hop_idx = -1;
};

// Runtime state at a given sample: which position index, and whether on.
struct CompState {
  bool present = false; // inside its start/stop window (what the ground truth records)
  bool on = false;      // emitting right now (a duty-cycled incumbent is present while off)
  int pos = 0;
};

class Scenario {
 public:
  Cell cell;
  std::string name;
  double noise_dbfs = -200;
  double noise_sigma = 0; // per I and Q, counts
  uint64_t seed = 1;
  double duration_s = 0;
  std::vector<Component> comps;

  void load(const std::string &path, const Cell &c, bool have_noise_override, double noise_override)
  {
    cell = c;
    std::ifstream f(path);
    if (!f)
      throw std::runtime_error("cannot open scenario " + path);
    json j = json::parse(f, nullptr, true, true);
    name = j.value("name", path);
    seed = j.value("seed", 1);
    duration_s = j.value("duration_s", 0.0);
    if (j.contains("noise_dbfs") && !j["noise_dbfs"].is_null())
      noise_dbfs = j["noise_dbfs"].get<double>();
    if (have_noise_override)
      noise_dbfs = noise_override;
    // total complex noise power = amp^2; per component sigma = amp / sqrt(2)
    noise_sigma = noise_dbfs > -150 ? dbfs_to_amp(noise_dbfs) / std::sqrt(2.0) : 0.0;

    for (auto &jc : j.at("components")) {
      Component k;
      k.id = jc.value("id", "c" + std::to_string(comps.size()));
      k.shape = jc.value("shape", "tone");
      if (k.shape != "tone" && k.shape != "sweep")
        throw std::runtime_error("component " + k.id + ": shape must be tone or sweep");
      k.start_s = jc.value("start_s", 0.0);
      k.stop_s = jc.value("stop_s", 1e18);
      k.amp_dbfs = jc.at("amplitude_dbfs").get<double>();
      k.amp = dbfs_to_amp(k.amp_dbfs);
      k.width_prb = jc.value("width_prb", 1.0);
      k.sweep_period_us = jc.value("sweep_period_us", 50.0);
      k.phase0 = jc.value("phase", 0.0);
      k.offset_prb = jc.value("offset_prb", 0.0);
      if (jc.contains("hop")) {
        k.positions = jc["hop"].at("prbs").get<std::vector<double>>();
        k.hop_dwell_s = jc["hop"].at("dwell_s").get<double>();
        k.hop_seed = jc["hop"].value("seed", 1);
      } else {
        k.positions = {jc.at("prb").get<double>()};
      }
      if (k.positions.empty())
        throw std::runtime_error("component " + k.id + ": no PRB position");
      for (double p : k.positions) {
        double hi = p + (k.shape == "sweep" ? k.width_prb : 1.0);
        if (p < 0 || hi > cell.num_prbs)
          throw std::runtime_error("component " + k.id + ": PRBs outside the carrier");
      }
      if (jc.contains("duty")) {
        k.duty = true;
        k.duty_period_s = jc["duty"].at("period_ms").get<double>() * 1e-3;
        k.duty_on_s = jc["duty"].at("on_ms").get<double>() * 1e-3;
        k.duty_offset_s = jc["duty"].value("offset_ms", 0.0) * 1e-3;
      }
      double fs = cell.sample_rate;
      k.start_n = (uint64_t)std::llround(k.start_s * fs);
      k.stop_n = k.stop_s >= 1e17 ? UINT64_MAX : (uint64_t)std::llround(k.stop_s * fs);
      k.dwell_n = (uint64_t)std::llround(k.hop_dwell_s * fs);
      k.duty_period_n = (uint64_t)std::llround(k.duty_period_s * fs);
      k.duty_on_n = (uint64_t)std::llround(k.duty_on_s * fs);
      k.duty_off_n = (uint64_t)std::llround(k.duty_offset_s * fs);
      k.sweep_n = std::max<uint64_t>(2, 2 * (uint64_t)std::llround(k.sweep_period_us * 1e-6 * fs / 2));
      k.hop_idx = (int)(splitmix64(k.hop_seed) % k.positions.size());
      comps.push_back(k);
    }
  }

  // Hop number h picks a new position that differs from the previous one. The sequence is
  // a function of the seed only; it is advanced incrementally because time never goes back.
  int hop_index(const Component &k, uint64_t n) const
  {
    if (k.positions.size() == 1 || k.dwell_n == 0 || n < k.start_n)
      return 0;
    uint64_t h = (n - k.start_n) / k.dwell_n;
    int sz = (int)k.positions.size();
    if (h < k.hop_h) {
      k.hop_h = 0;
      k.hop_idx = (int)(splitmix64(k.hop_seed) % sz);
    }
    while (k.hop_h < h) {
      k.hop_h++;
      k.hop_idx = (k.hop_idx + 1 + (int)(splitmix64(k.hop_seed ^ (k.hop_h * 0x9e3779b97f4a7c15ULL)) % (sz - 1))) % sz;
    }
    return k.hop_idx;
  }

  CompState state_at(const Component &k, uint64_t n) const
  {
    CompState s;
    if (n < k.start_n || n >= k.stop_n)
      return s;
    s.pos = hop_index(k, n);
    s.present = true;
    s.on = true;
    if (k.duty && k.duty_period_n > 0)
      s.on = ((n + k.duty_off_n) % k.duty_period_n) < k.duty_on_n;
    return s;
  }

  // First sample after n at which the state of k may change.
  uint64_t next_edge(const Component &k, uint64_t n) const
  {
    uint64_t e = UINT64_MAX;
    if (n < k.start_n)
      e = std::min(e, k.start_n);
    if (n < k.stop_n)
      e = std::min(e, k.stop_n);
    if (n >= k.start_n && k.positions.size() > 1 && k.dwell_n > 0)
      e = std::min(e, k.start_n + ((n - k.start_n) / k.dwell_n + 1) * k.dwell_n);
    if (k.duty && k.duty_period_n > 0) {
      uint64_t p = (n + k.duty_off_n) % k.duty_period_n;
      e = std::min(e, p < k.duty_on_n ? n + (k.duty_on_n - p) : n + (k.duty_period_n - p));
    }
    return e;
  }

  // PRB indices a component occupies for position index pi.
  std::vector<int> prbs_of(const Component &k, int pi) const
  {
    std::vector<int> v;
    double p = k.positions[pi];
    if (k.shape == "tone") {
      v.push_back((int)std::floor(p));
    } else {
      for (int i = 0; i < (int)std::llround(k.width_prb); i++)
        v.push_back((int)std::floor(p) + i);
    }
    return v;
  }

  // Add component k over [n0, n0+len) into acc (interleaved float I,Q), sample offset o.
  void add_segment(const Component &k, int pi, uint64_t n0, size_t len, float *acc) const
  {
    const double fs = cell.sample_rate;
    const float A = (float)k.amp;
    const double p = k.positions[pi];
    if (k.shape == "tone") {
      // A tone sits at the centre of PRB floor(p), shifted by offset_prb PRBs (-0.5 .. 0.5).
      double f = cell.freq_of_prb_pos(std::floor(p) + 0.5 + k.offset_prb);
      int64_t fcw = (int64_t)std::llround(f / fs * 4294967296.0);
      uint32_t ph = (uint32_t)((uint64_t)fcw * n0) + (uint32_t)(k.phase0 * 4294967296.0);
      uint32_t inc = (uint32_t)fcw;
      for (size_t i = 0; i < len; i++) {
        uint32_t idx = ph >> (32 - kTableBits);
        acc[2 * i] += A * g_cos[idx];
        acc[2 * i + 1] += A * g_sin[idx];
        ph += inc;
      }
    } else {
      // Triangle sweep over the band: continuous phase and frequency, so little splatter outside it.
      double f_lo = cell.freq_of_prb_pos(std::floor(p));
      double f_hi = cell.freq_of_prb_pos(std::floor(p) + k.width_prb);
      const uint64_t P = k.sweep_n, H = P / 2;
      const double lo = f_lo / fs, hi = f_hi / fs;
      const double kc = (hi - lo) / (double)H; // cycles/sample^2
      const double per_period = (double)P * (lo + hi) / 2.0; // phase gained per full period, cycles
      uint64_t m = n0 / P, idx0 = n0 % P;
      double within, fnow, dslope;
      if (idx0 < H) {
        double t = (double)idx0;
        within = lo * t + 0.5 * kc * t * t;
        fnow = lo + kc * t;
        dslope = kc;
      } else {
        double j = (double)(idx0 - H);
        within = (double)H * (lo + hi) / 2.0 + hi * j - 0.5 * kc * j * j;
        fnow = hi - kc * j;
        dslope = -kc;
      }
      double pc = std::fmod((double)m * per_period, 1.0) + within;
      pc -= std::floor(pc);
      uint32_t ph = (uint32_t)(pc * 4294967296.0);
      auto to_fcw = [](double f) { return (uint32_t)(int32_t)std::llround(f * 4294967296.0); };
      uint32_t fcw = to_fcw(fnow);
      uint32_t dfcw = (uint32_t)(int32_t)std::llround(dslope * 4294967296.0);
      const uint32_t dfcw_up = (uint32_t)(int32_t)std::llround(kc * 4294967296.0);
      const uint32_t dfcw_dn = (uint32_t)(-(int32_t)std::llround(kc * 4294967296.0));
      uint64_t idx = idx0;
      for (size_t i = 0; i < len; i++) {
        uint32_t ti = ph >> (32 - kTableBits);
        acc[2 * i] += A * g_cos[ti];
        acc[2 * i + 1] += A * g_sin[ti];
        ph += fcw;
        fcw += dfcw;
        if (++idx == H) {
          dfcw = dfcw_dn;
        } else if (idx == P) {
          idx = 0;
          dfcw = dfcw_up;
          fcw = to_fcw(lo);
        }
      }
    }
  }
};

struct EventLog {
  std::ofstream f;
  bool open = false;
  void init(const std::string &path)
  {
    if (path.empty())
      return;
    f.open(path, std::ios::out | std::ios::trunc);
    open = f.good();
  }
};

int64_t wall_ns()
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
}

bool read_full(int fd, void *buf, size_t n)
{
  char *p = (char *)buf;
  while (n) {
    ssize_t r = recv(fd, p, n, 0);
    if (r <= 0)
      return false;
    p += r;
    n -= (size_t)r;
  }
  return true;
}

bool write_full(int fd, const void *buf, size_t n)
{
  const char *p = (const char *)buf;
  while (n) {
    ssize_t r = send(fd, p, n, MSG_NOSIGNAL);
    if (r <= 0)
      return false;
    p += r;
    n -= (size_t)r;
  }
  return true;
}

// Generates the incumbent signal and the noise for [n0, n0+len); output as int16 IQ.
class Generator {
 public:
  Generator(const Scenario &s) : sc(s), last(s.comps.size()), have_last(s.comps.size(), false) {}
  const Scenario &sc;
  uint64_t n_ref = 0; // first sample timestamp seen = scenario time zero
  bool have_ref = false;
  int64_t wall_ref_ns = 0;
  EventLog *events = nullptr;
  std::vector<CompState> last;
  std::vector<bool> have_last;
  bool have_tick = false;
  uint64_t last_tick = 0;

  void log_event(size_t ci, const CompState &st, uint64_t n)
  {
    const Component &k = sc.comps[ci];
    double t = (double)(n - n_ref) / sc.cell.sample_rate;
    json e;
    e["t_s"] = t;
    e["wall_unix_ns"] = wall_ns();
    e["id"] = k.id;
    e["state"] = st.present ? "on" : "off";
    e["shape"] = k.shape;
    e["amplitude_dbfs"] = k.amp_dbfs;
    e["prbs"] = st.present ? sc.prbs_of(k, st.pos) : std::vector<int>{};
    std::string line = e.dump();
    std::printf("[INJ] %s\n", line.c_str());
    std::fflush(stdout);
    if (events && events->open) {
      events->f << line << "\n";
      events->f.flush();
    }
  }

  // n is an absolute sample timestamp; scenario time zero is the first timestamp passed in.
  void generate(uint64_t n_abs, size_t len, int16_t *out, std::vector<float> &acc)
  {
    if (!have_ref) {
      n_ref = n_abs;
      have_ref = true;
      wall_ref_ns = wall_ns();
      json h;
      h["scenario"] = sc.name;
      h["scenario_start_wall_unix_ns"] = wall_ref_ns;
      h["sample_rate"] = sc.cell.sample_rate;
      h["noise_dbfs"] = sc.noise_dbfs;
      std::printf("[INJ] {\"start\":%s}\n", h.dump().c_str());
      if (events && events->open) {
        events->f << h.dump() << "\n";
        events->f.flush();
      }
    }
    uint64_t n0 = n_abs - n_ref; // scenario sample index
    // One tick per second of sample time, so a scorer can map wall-clock log times to sample time.
    if (events && events->open) {
      uint64_t sec = (uint64_t)((double)n0 / sc.cell.sample_rate);
      if (!have_tick || sec != last_tick) {
        have_tick = true;
        last_tick = sec;
        events->f << "{\"tick\":true,\"t_s\":" << (double)n0 / sc.cell.sample_rate << ",\"wall_unix_ns\":" << wall_ns() << "}\n";
        events->f.flush();
      }
    }
    acc.assign(2 * len, 0.0f);
    for (size_t ci = 0; ci < sc.comps.size(); ci++) {
      const Component &k = sc.comps[ci];
      uint64_t n = n0, end = n0 + len;
      while (n < end) {
        CompState st = sc.state_at(k, n);
        if (!have_last[ci] || st.present != last[ci].present || (st.present && st.pos != last[ci].pos)) {
          if (have_last[ci] || st.present)
            log_event(ci, st, n + n_ref);
          last[ci] = st;
          have_last[ci] = true;
        }
        uint64_t e = std::min(sc.next_edge(k, n), end);
        if (e <= n)
          e = end;
        if (st.on)
          sc.add_segment(k, st.pos, n, (size_t)(e - n), acc.data() + 2 * (n - n0));
        n = e;
      }
    }
    if (sc.noise_sigma > 0) {
      uint32_t x = (uint32_t)(splitmix64(sc.seed ^ n_abs) | 1u);
      const float s = (float)sc.noise_sigma;
      for (size_t i = 0; i < len; i++) {
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        acc[2 * i] += s * g_gauss[x & 0xFFFF];
        acc[2 * i + 1] += s * g_gauss[x >> 16];
      }
    }
    for (size_t i = 0; i < 2 * len; i++) {
      float v = acc[i];
      v = v > 32767.f ? 32767.f : (v < -32768.f ? -32768.f : v);
      out[i] = (int16_t)std::lrintf(v);
    }
  }
};

void usage(const char *a0)
{
  std::fprintf(stderr,
               "usage: %s --scenario FILE [options]\n"
               "  --server ADDR          rfsimulator server address (default 127.0.0.1)\n"
               "  --port N               rfsimulator server port (default 4043)\n"
               "  --sample-rate HZ       gNB sample rate (default 61440000; 46080000 with -E)\n"
               "  --num-prbs N           carrier size in PRBs (default 106)\n"
               "  --scs HZ               subcarrier spacing (default 30000)\n"
               "  --noise-dbfs DB        override the scenario noise level\n"
               "  --dump-at S FILE       write the first reply block at scenario time S (seconds) to FILE, for debugging\n"
               "  --verbose              print DL block statistics once per second of sample time\n"
               "  --speed X              pace the simulation to X times real time (default 1; 0 = as fast as possible)\n"
               "  --events FILE          write ground-truth events as JSON lines\n"
               "  --offline-seconds S    do not connect; write S seconds of signal\n"
               "  --out-iq FILE          with --offline-seconds: raw int16 IQ output\n",
               a0);
}

} // namespace

int main(int argc, char **argv)
{
  std::string scen, server = "127.0.0.1", events_path, out_iq;
  int port = 4043;
  Cell cell;
  bool noise_override = false;
  double noise_dbfs = 0, offline_s = 0, speed = 1.0;
  bool verbose = false;
  double dump_at = -1;
  std::string dump_file;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto need = [&](const char *nm) -> const char * {
      if (i + 1 >= argc) {
        std::fprintf(stderr, "%s needs a value\n", nm);
        std::exit(2);
      }
      return argv[++i];
    };
    if (a == "--scenario") scen = need("--scenario");
    else if (a == "--server") server = need("--server");
    else if (a == "--port") port = std::atoi(need("--port"));
    else if (a == "--sample-rate") cell.sample_rate = std::atof(need("--sample-rate"));
    else if (a == "--num-prbs") cell.num_prbs = std::atoi(need("--num-prbs"));
    else if (a == "--scs") cell.scs_hz = std::atof(need("--scs"));
    else if (a == "--noise-dbfs") { noise_override = true; noise_dbfs = std::atof(need("--noise-dbfs")); }
    else if (a == "--verbose") verbose = true;
    else if (a == "--dump-at") { dump_at = std::atof(need("--dump-at")); dump_file = need("--dump-at FILE"); }
    else if (a == "--speed") speed = std::atof(need("--speed"));
    else if (a == "--events") events_path = need("--events");
    else if (a == "--offline-seconds") offline_s = std::atof(need("--offline-seconds"));
    else if (a == "--out-iq") out_iq = need("--out-iq");
    else { usage(argv[0]); return 2; }
  }
  if (scen.empty()) {
    usage(argv[0]);
    return 2;
  }
  init_tables();
  Scenario sc;
  try {
    sc.load(scen, cell, noise_override, noise_dbfs);
  } catch (const std::exception &e) {
    std::fprintf(stderr, "scenario error: %s\n", e.what());
    return 2;
  }
  EventLog events;
  events.init(events_path);
  Generator gen(sc);
  gen.events = &events;
  std::vector<float> acc;

  if (offline_s > 0) {
    FILE *fo = out_iq.empty() ? nullptr : std::fopen(out_iq.c_str(), "wb");
    const size_t blk = (size_t)(cell.sample_rate * 0.0005); // one slot at 30 kHz SCS
    std::vector<int16_t> buf(2 * blk);
    uint64_t total = (uint64_t)(offline_s * cell.sample_rate), n = 0;
    while (n < total) {
      size_t len = (size_t)std::min<uint64_t>(blk, total - n);
      gen.generate(n, len, buf.data(), acc);
      if (fo)
        std::fwrite(buf.data(), 4, len, fo);
      n += len;
    }
    if (fo)
      std::fclose(fo);
    return 0;
  }

  int fd = -1;
  for (int attempt = 0; attempt < 600; attempt++) {
    fd = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in sa{};
    sa.sin_family = AF_INET;
    sa.sin_port = htons(port);
    inet_pton(AF_INET, server.c_str(), &sa.sin_addr);
    if (connect(fd, (sockaddr *)&sa, sizeof(sa)) == 0)
      break;
    close(fd);
    fd = -1;
    if (attempt == 0)
      std::fprintf(stderr, "waiting for the gNB RF simulator on %s:%d ...\n", server.c_str(), port);
    sleep(1);
  }
  if (fd < 0) {
    std::fprintf(stderr, "could not connect\n");
    return 1;
  }
  int one = 1;
  setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
  std::printf("[INJ] connected to %s:%d, scenario '%s', noise %.1f dBFS\n", server.c_str(), port, sc.name.c_str(), sc.noise_dbfs);

  std::vector<char> scratch;
  std::vector<int16_t> out;
  uint64_t blocks = 0, pace_n0 = 0;
  bool paced = false;
  uint64_t prev_end = 0, gaps = 0, stat_ts = 0, min_sz = UINT64_MAX, max_sz = 0;
  int64_t last_gap = 0;
  std::chrono::steady_clock::time_point pace_t0;
  while (true) {
    BlockHeader h;
    if (!read_full(fd, &h, sizeof(h)))
      break;
    size_t payload = (size_t)h.nbAnt * 4 + (size_t)h.nbAnt * h.size * 4;
    scratch.resize(payload);
    if (!read_full(fd, scratch.data(), payload))
      break;
    // Reply: one antenna, zero gain, same timestamp and size.
    BlockHeader r{h.size, 1, h.timestamp, 0, 0};
    float gain = 0.0f;
    out.resize(2 * (size_t)h.size);
    if (speed > 0) {
      // The gNB waits for our reply, so delaying it paces the whole simulation.
      if (!paced) {
        paced = true;
        pace_t0 = std::chrono::steady_clock::now();
        pace_n0 = h.timestamp;
      }
      auto due = pace_t0 + std::chrono::nanoseconds((int64_t)((double)(h.timestamp - pace_n0) / cell.sample_rate / speed * 1e9));
      std::this_thread::sleep_until(due);
    }
    gen.generate(h.timestamp, h.size, out.data(), acc);
    if (dump_at >= 0 && gen.have_ref && (double)(h.timestamp - gen.n_ref) / cell.sample_rate >= dump_at) {
      if (FILE *fd2 = std::fopen(dump_file.c_str(), "wb")) {
        std::fwrite(out.data(), 4, h.size, fd2);
        std::fclose(fd2);
        std::printf("[INJ] dumped block ts=%llu size=%u to %s\n", (unsigned long long)h.timestamp, h.size, dump_file.c_str());
      }
      dump_at = -1;
    }
    if (!write_full(fd, &r, sizeof(r)) || !write_full(fd, &gain, sizeof(gain)) || !write_full(fd, out.data(), (size_t)h.size * 4))
      break;
    blocks++;
    if (verbose) {
      if (blocks > 1 && h.timestamp != prev_end)
        gaps++, last_gap = (int64_t)h.timestamp - (int64_t)prev_end;
      prev_end = h.timestamp + h.size;
      min_sz = std::min<uint64_t>(min_sz, h.size);
      max_sz = std::max<uint64_t>(max_sz, h.size);
      if (h.timestamp - stat_ts >= (uint64_t)cell.sample_rate) {
        std::printf("[INJ] blocks=%llu size=[%llu..%llu] gaps=%llu last_gap=%lld ts=%llu nbAnt=%u opt=%u/%u\n", (unsigned long long)blocks,
                    (unsigned long long)min_sz, (unsigned long long)max_sz, (unsigned long long)gaps, (long long)last_gap,
                    (unsigned long long)h.timestamp, h.nbAnt, h.option_value, h.option_flag);
        std::fflush(stdout);
        stat_ts = h.timestamp;
        min_sz = UINT64_MAX;
        max_sz = 0;
      }
    }
    if (sc.duration_s > 0 && gen.have_ref && (double)(h.timestamp - gen.n_ref) / cell.sample_rate > sc.duration_s) {
      std::printf("[INJ] scenario duration reached\n");
      break;
    }
  }
  std::printf("[INJ] stopped after %llu blocks\n", (unsigned long long)blocks);
  close(fd);
  return 0;
}
