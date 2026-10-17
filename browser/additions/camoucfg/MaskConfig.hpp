/*
Helper to extract values from the CAMOU_CONFIG environment variable(s).
Written by daijro.
*/

#pragma once
#include "json.hpp"
#include <memory>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>
#include <cstdint>
#include <optional>
#include <codecvt>
#include "mozilla/glue/Debug.h"
#include <cstdlib>
#include <cstdio>
#include <mutex>
#include <variant>
#include <cstddef>
#include <vector>
#include <unordered_map>
#include <cstring>
#include <algorithm>

#ifdef _WIN32
#  include <windows.h>
#endif

namespace MaskConfig {

// Function to get the value of an environment variable as a UTF-8 string.
inline std::optional<std::string> get_env_utf8(const std::string& name) {
#ifdef _WIN32
  std::wstring wName(name.begin(), name.end());
  DWORD size = GetEnvironmentVariableW(wName.c_str(), nullptr, 0);
  if (size == 0) return std::nullopt;  // Environment variable not found

  std::vector<wchar_t> buffer(size);
  GetEnvironmentVariableW(wName.c_str(), buffer.data(), size);
  std::wstring wValue(buffer.data());

  // Convert UTF-16 to UTF-8
  std::wstring_convert<std::codecvt_utf8_utf16<wchar_t>> converter;
  return converter.to_bytes(wValue);
#else
  const char* value = std::getenv(name.c_str());
  if (!value) return std::nullopt;
  return std::string(value);
#endif
}

inline nlohmann::json LoadJson() {
  nlohmann::json jsonConfig;
  {
    std::string jsonString;
    int index = 1;

    while (true) {
      std::string envName = "CAMOU_CONFIG_" + std::to_string(index);
      auto partialConfig = get_env_utf8(envName);
      if (!partialConfig) break;

      jsonString += *partialConfig;
      index++;
    }

    if (jsonString.empty()) {
      // Check for the original CAMOU_CONFIG as fallback
      auto originalConfig = get_env_utf8("CAMOU_CONFIG");
      if (originalConfig) jsonString = *originalConfig;
    }

    if (jsonString.empty()) {
      return nlohmann::json{};
    }

    // Validate
    if (!nlohmann::json::accept(jsonString)) {
      printf_stderr("ERROR: Invalid JSON passed to CAMOU_CONFIG!\n");
      return nlohmann::json{};
    }

    jsonConfig = nlohmann::json::parse(jsonString);
  }
  return jsonConfig;
}

// The config is parsed once and never changes. Spoofed getters read it on
// every call (screen.width, devicePixelRatio, WebGL getParameter...), so a
// lookup has to cost about what the stock getter does: a function-local
// static instead of std::call_once, and one search per key through a
// string_view, where each getter used to build a std::string (a heap
// allocation) and search two or three times. Measured in the browser against
// stock Firefox 152.0.4 before this: screen.availWidth 1211 ns vs 239 ns,
// devicePixelRatio 134 ns vs 40 ns, from script, which a page can time.
inline const nlohmann::json& GetJson() {
  static const nlohmann::json jsonConfig = LoadJson();
  return jsonConfig;
}

// Hash indexes over the config's keys, built once. json objects are ordered
// maps, and walking one per lookup cost ~40 ns against a 52-key launch config
// (std::unordered_map still ~24 ns) -- as much as a whole stock getter like
// devicePixelRatio. This table is open-addressed at under half load, hashes
// the length and the first and last 8 bytes, and confirms with one compare:
// ~5 ns. The string_views point at the parsed config's own keys, which live
// as long as it does. Indexed: the top level, and every object directly under
// it (the WebGL parameter tables and the like).
template <typename V>
class FlatIndex {
 public:
  FlatIndex() = default;

  explicit FlatIndex(size_t aCount) {
    size_t capacity = 16;
    while (capacity < aCount * 2 + 1) capacity *= 2;
    mSlots.assign(capacity, Slot{});
    mMask = capacity - 1;
  }

  // `value` must be non-null; keys must be unique and outlive the index.
  void Insert(std::string_view key, V value) {
    size_t i = Hash(key) & mMask;
    while (mSlots[i].value) i = (i + 1) & mMask;
    mSlots[i] = Slot{key, value};
  }

  V Find(std::string_view key) const {
    if (mSlots.empty()) return nullptr;
    for (size_t i = Hash(key) & mMask; mSlots[i].value; i = (i + 1) & mMask) {
      if (mSlots[i].key == key) return mSlots[i].value;
    }
    return nullptr;
  }

 private:
  struct Slot {
    std::string_view key;
    V value = nullptr;
  };

  static size_t Hash(std::string_view key) {
    uint64_t head = 0;
    uint64_t tail = 0;
    size_t n = key.size();
    if (n >= 8) {
      std::memcpy(&head, key.data(), 8);
      std::memcpy(&tail, key.data() + n - 8, 8);
    } else {
      std::memcpy(&head, key.data(), n);
    }
    uint64_t h = (head * 0x9E3779B97F4A7C15ULL) ^ ((tail + n) * 0xC2B2AE3D27D4EB4FULL);
    return static_cast<size_t>(h ^ (h >> 31));
  }

  std::vector<Slot> mSlots;
  size_t mMask = 0;
};

using KeyIndex = FlatIndex<const nlohmann::json*>;

inline KeyIndex IndexObject(const nlohmann::json& obj) {
  KeyIndex index(obj.size());
  for (auto it = obj.begin(); it != obj.end(); ++it) {
    index.Insert(std::string_view(it.key()), &*it);
  }
  return index;
}

// WebGL parameter tables keyed by the enum itself. getParameter is answered
// from them on every call, and formatting the enum into a decimal key and
// hashing two strings per call still left MAX_TEXTURE_SIZE at 49 ns against
// stock's 13 ns. An integer probe does not format or hash a string.
class EnumIndex {
 public:
  EnumIndex() = default;

  explicit EnumIndex(const nlohmann::json& table) {
    size_t capacity = 16;
    while (capacity < table.size() * 2 + 1) capacity *= 2;
    mSlots.assign(capacity, Slot{});
    mMask = capacity - 1;
    for (auto it = table.begin(); it != table.end(); ++it) {
      uint32_t pname = 0;
      if (!ParseEnum(it.key(), pname)) continue;
      size_t i = Hash(pname) & mMask;
      while (mSlots[i].value) i = (i + 1) & mMask;
      mSlots[i] = Slot{pname, &*it};
    }
  }

  const nlohmann::json* Find(uint32_t pname) const {
    if (mSlots.empty()) return nullptr;
    for (size_t i = Hash(pname) & mMask; mSlots[i].value; i = (i + 1) & mMask) {
      if (mSlots[i].pname == pname) return mSlots[i].value;
    }
    return nullptr;
  }

 private:
  struct Slot {
    uint32_t pname = 0;
    const nlohmann::json* value = nullptr;
  };

  // Only canonical decimal keys ("3379"): the string lookup they replace
  // matched exactly that spelling.
  static bool ParseEnum(const std::string& key, uint32_t& out) {
    if (key.empty() || key.size() > 10 || (key.size() > 1 && key[0] == '0')) {
      return false;
    }
    uint64_t value = 0;
    for (char c : key) {
      if (c < '0' || c > '9') return false;
      value = value * 10 + static_cast<uint64_t>(c - '0');
    }
    if (value > UINT32_MAX) return false;
    out = static_cast<uint32_t>(value);
    return true;
  }

  static size_t Hash(uint32_t pname) {
    return static_cast<size_t>((static_cast<uint64_t>(pname) * 0x9E3779B97F4A7C15ULL) >> 32);
  }

  std::vector<Slot> mSlots;
  size_t mMask = 0;
};

struct ConfigIndex {
  EnumIndex glParams;
  EnumIndex gl2Params;
  KeyIndex top;
  // Every object directly under the top level, by address (Find(obj, key))
  // and by name (FindNested, the WebGL getParameter path).
  std::unordered_map<const nlohmann::json*, KeyIndex> tables;
  FlatIndex<const KeyIndex*> tablesByName;
};

inline const ConfigIndex& GetIndex() {
  static const ConfigIndex index = [] {
    ConfigIndex built;
    const auto& data = GetJson();
    if (!data.is_object()) return built;
    built.top = IndexObject(data);
    for (const auto& value : data) {
      if (value.is_object()) built.tables.emplace(&value, IndexObject(value));
    }
    for (auto [name, target] : {std::pair{"webGl:parameters", &built.glParams},
                                std::pair{"webGl2:parameters", &built.gl2Params}}) {
      const auto* table = built.top.Find(name);
      if (table && table->is_object()) *target = EnumIndex(*table);
    }
    // unordered_map nodes do not move, so these pointers stay valid.
    built.tablesByName = FlatIndex<const KeyIndex*>(built.tables.size());
    for (auto it = data.begin(); it != data.end(); ++it) {
      auto table = built.tables.find(&*it);
      if (table != built.tables.end()) {
        built.tablesByName.Insert(std::string_view(it.key()), &table->second);
      }
    }
    return built;
  }();
  return index;
}

// The value stored under `key` in `obj`, or null when `obj` is not an object
// or has no such key. Never allocates.
inline const nlohmann::json* Find(const nlohmann::json& obj,
                                  std::string_view key) {
  if (!obj.is_object()) return nullptr;
  const auto& index = GetIndex();
  if (&obj == &GetJson()) return index.top.Find(key);
  auto table = index.tables.find(&obj);
  if (table != index.tables.end()) return table->second.Find(key);
  auto it = obj.find(key);
  return it == obj.end() ? nullptr : &*it;
}

inline const nlohmann::json* Find(std::string_view key) {
  return GetIndex().top.Find(key);
}

inline bool HasKey(std::string_view key, const nlohmann::json& data) {
  return Find(data, key) != nullptr;
}

inline std::optional<std::string> GetString(std::string_view key) {
  const auto* value = Find(key);
  if (!value) return std::nullopt;
  return value->get<std::string>();
}

inline std::vector<std::string> GetStringList(std::string_view key) {
  std::vector<std::string> result;
  const auto* value = Find(key);
  if (!value) return {};
  for (const auto& item : *value) {
    result.push_back(item.get<std::string>());
  }
  return result;
}

inline std::vector<std::string> GetStringListLower(std::string_view key) {
  std::vector<std::string> result = GetStringList(key);
  for (auto& str : result) {
    std::transform(str.begin(), str.end(), str.begin(),
                   [](unsigned char c) { return std::tolower(c); });
  }
  return result;
}

/**
 * The spoofed font family allowlist ("fonts"), lowercased and cached for the
 * lifetime of the process. CAMOU_CONFIG is read once at startup and never
 * changes, and the gfx font lookup paths consult this on every family
 * resolution, so re-parsing the JSON per call is not an option.
 * An empty list means no font spoofing is configured.
 */
inline const std::vector<std::string>& FontAllowlist() {
  static const std::vector<std::string> fonts = GetStringListLower("fonts");
  return fonts;
}

inline bool HasFontAllowlist() { return !FontAllowlist().empty(); }

/**
 * Whether a font family may be used. `family` must already be lowercased
 * (gfxPlatformFontList::GenerateFontListKey output is). Always true when no
 * allowlist is configured.
 */
inline bool IsFontAllowed(std::string_view family) {
  const auto& fonts = FontAllowlist();
  if (fonts.empty()) return true;
  return std::find(fonts.begin(), fonts.end(), family) != fonts.end();
}

template <typename T>
inline std::optional<T> GetUintImpl(std::string_view key) {
  const auto* value = Find(key);
  if (!value) return std::nullopt;
  if (value->is_number_unsigned()) return value->get<T>();
  printf_stderr("ERROR: Value for key '%.*s' is not an unsigned integer\n",
                static_cast<int>(key.size()), key.data());
  return std::nullopt;
}

inline std::optional<uint64_t> GetUint64(std::string_view key) {
  return GetUintImpl<uint64_t>(key);
}

inline std::optional<uint32_t> GetUint32(std::string_view key) {
  return GetUintImpl<uint32_t>(key);
}

inline std::optional<int32_t> GetInt32(std::string_view key) {
  const auto* value = Find(key);
  if (!value) return std::nullopt;
  if (value->is_number_integer()) return value->get<int32_t>();
  printf_stderr("ERROR: Value for key '%.*s' is not an integer\n",
                static_cast<int>(key.size()), key.data());
  return std::nullopt;
}

inline std::optional<double> GetDouble(std::string_view key) {
  const auto* value = Find(key);
  if (!value) return std::nullopt;
  if (value->is_number_float()) return value->get<double>();
  if (value->is_number_unsigned() || value->is_number_integer())
    return static_cast<double>(value->get<int64_t>());
  printf_stderr("ERROR: Value for key '%.*s' is not a double\n",
                static_cast<int>(key.size()), key.data());
  return std::nullopt;
}

// For the rare caller that must tell an unset key from false. A plain
// std::optional<bool> in a condition tests presence, not the value, so the
// common case is GetBool below.
inline std::optional<bool> GetOptionalBool(std::string_view key) {
  const auto* value = Find(key);
  if (!value) return std::nullopt;
  if (value->is_boolean()) return value->get<bool>();
  printf_stderr("ERROR: Value for key '%.*s' is not a boolean\n",
                static_cast<int>(key.size()), key.data());
  return std::nullopt;
}

inline bool GetBool(std::string_view key) {
  return GetOptionalBool(key).value_or(false);
}

// The OS an identity presents, from its navigator.platform. None means no
// platform is configured; Other, one no identity uses.
enum class SpoofedOS { None, Windows, MacOS, Linux, Other };

inline SpoofedOS SpoofedOSFor(std::string_view platform) {
  if (platform == "Win32") return SpoofedOS::Windows;
  if (platform == "MacIntel") return SpoofedOS::MacOS;
  if (platform.rfind("Linux", 0) == 0) return SpoofedOS::Linux;
  return SpoofedOS::Other;
}

// The launch's OS. Only process-wide decisions use it; anything a page of one
// context can observe asks NavigatorManager::GetSpoofedOS for that context's.
inline SpoofedOS GetSpoofedOS() {
  static const SpoofedOS os = [] {
    auto platform = GetString("navigator.platform");
    return platform ? SpoofedOSFor(*platform) : SpoofedOS::None;
  }();
  return os;
}

// The ephemeral port range of an OS, which is where its kernel puts a socket
// bound to port 0. A page sees these ports in WebRTC candidates.
inline std::optional<std::pair<uint16_t, uint16_t>> SpoofedEphemeralPorts(
    SpoofedOS aOS = GetSpoofedOS()) {
  switch (aOS) {
    case SpoofedOS::Windows:
    case SpoofedOS::MacOS:
      return std::pair<uint16_t, uint16_t>{49152, 65535};
    case SpoofedOS::Linux:
      // The kernel's default net.ipv4.ip_local_port_range.
      return std::pair<uint16_t, uint16_t>{32768, 60999};
    default:
      return std::nullopt;
  }
}

inline std::optional<std::array<uint32_t, 4>> GetRect(std::string_view left,
                                                     std::string_view top,
                                                     std::string_view width,
                                                     std::string_view height) {
  std::array<std::optional<uint32_t>, 4> values = {
      GetUint32(left).value_or(0), GetUint32(top).value_or(0), GetUint32(width),
      GetUint32(height)};

  if (!values[2].has_value() || !values[3].has_value()) {
    if (values[2].has_value() ^ values[3].has_value())
      printf_stderr(
          "Both %.*s and %.*s must be provided. Using default behavior.\n",
          static_cast<int>(height.size()), height.data(),
          static_cast<int>(width.size()), width.data());
    return std::nullopt;
  }

  std::array<uint32_t, 4> result;
  std::transform(values.begin(), values.end(), result.begin(),
                 [](const auto& value) { return value.value(); });

  return result;
}

// Helpers for WebGL

// The node at config[domain][key], or null. WebGL answers getParameter from
// these tables on every call, so this returns a pointer into the parsed
// config rather than a copy.
inline const nlohmann::json* FindNested(std::string_view domain,
                                        std::string_view key) {
  const KeyIndex* table = GetIndex().tablesByName.Find(domain);
  return table ? table->Find(key) : nullptr;
}

// The webGl[2]:parameters entry for a WebGL enum, or null.
inline const nlohmann::json* FindGLParam(uint32_t pname, bool isWebGL2) {
  const auto& index = GetIndex();
  return (isWebGL2 ? index.gl2Params : index.glParams).Find(pname);
}

inline std::optional<nlohmann::json> GetNested(std::string_view domain,
                                               std::string_view keyStr) {
  if (const auto* value = FindNested(domain, keyStr)) return *value;
  return std::nullopt;
}

inline std::optional<
    std::variant<int64_t, bool, double, std::string, std::nullptr_t>>
GLParam(uint32_t pname, bool isWebGL2) {
  const auto* value = FindGLParam(pname, isWebGL2);
  if (!value) return std::nullopt;
  const auto& data = *value;
  if (data.is_null()) return std::nullptr_t();
  if (data.is_number_integer()) return data.get<int64_t>();
  if (data.is_boolean()) return data.get<bool>();
  if (data.is_number_float()) return data.get<double>();
  if (data.is_string()) return data.get<std::string>();
  return std::nullopt;
}

template <typename T>
inline T MParamGL(uint32_t pname, T defaultValue, bool isWebGL2) {
  if (const auto* value = FindGLParam(pname, isWebGL2)) {
    return value->get<T>();
  }
  return defaultValue;
}

inline std::optional<std::array<int32_t, 3UL>> MShaderData(
    uint32_t shaderType, uint32_t precisionType, bool isWebGL2) {
  std::string valueName =
      std::to_string(shaderType) + "," + std::to_string(precisionType);
  if (const auto* value =
          FindNested(isWebGL2 ? "webGl2:shaderPrecisionFormats"
                              : "webGl:shaderPrecisionFormats",
                     valueName)) {
    // Convert {rangeMin: int, rangeMax: int, precision: int} to array
    const auto& data = *value;
    // Assert rangeMin, rangeMax, and precision are present
    if (!data.contains("rangeMin") || !data.contains("rangeMax") ||
        !data.contains("precision")) {
      return std::nullopt;
    }
    return std::array<int32_t, 3U>{data["rangeMin"].get<int32_t>(),
                                   data["rangeMax"].get<int32_t>(),
                                   data["precision"].get<int32_t>()};
  }
  return std::nullopt;
}

inline std::optional<
    std::vector<std::tuple<std::string, std::string, std::string, bool, bool>>>
MVoices() {
  const auto& data = GetJson();
  if (!data.contains("voices") || !data["voices"].is_array()) {
    return std::nullopt;
  }

  std::vector<std::tuple<std::string, std::string, std::string, bool, bool>>
      voices;
  for (const auto& voice : data["voices"]) {
    // Each voice must be a full object with all five fields. A bare string
    // (e.g. "Name:lang:type") or an object missing a field registers NOTHING
    // and would silently leave the host's native voices exposed, so warn
    // loudly instead of dropping it quietly.
    if (!voice.is_object() || !voice.contains("lang") ||
        !voice.contains("name") || !voice.contains("voiceUri") ||
        !voice.contains("isDefault") || !voice.contains("isLocalService")) {
      printf_stderr(
          "ERROR: 'voices' entry is not a complete object "
          "{lang,name,voiceUri,isDefault,isLocalService}; skipping: %s\n",
          voice.dump().c_str());
      continue;
    }

    voices.emplace_back(
        voice["lang"].get<std::string>(), voice["name"].get<std::string>(),
        voice["voiceUri"].get<std::string>(), voice["isDefault"].get<bool>(),
        voice["isLocalService"].get<bool>());
  }
  return voices;
}

}  // namespace MaskConfig