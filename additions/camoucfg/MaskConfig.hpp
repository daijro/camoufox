/*
Helper to extract values from the CAMOU_CONFIG environment variable(s).
Written by daijro.
*/

#pragma once
#include "json.hpp"
#include <memory>
#include <string>
#include <tuple>
#include <optional>
#include <codecvt>
#include "mozilla/glue/Debug.h"
#include <cstdlib>
#include <cstdio>
#include <mutex>
#include <variant>
#include <cstddef>
#include <vector>
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

inline const nlohmann::json& GetJson() {
  static std::once_flag initFlag;
  static nlohmann::json jsonConfig;

  std::call_once(initFlag, []() {
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
      jsonConfig = nlohmann::json{};
      return;
    }

    // Validate
    if (!nlohmann::json::accept(jsonString)) {
      printf_stderr("ERROR: Invalid JSON passed to CAMOU_CONFIG!\n");
      jsonConfig = nlohmann::json{};
      return;
    }

    jsonConfig = nlohmann::json::parse(jsonString);
  });

  return jsonConfig;
}

inline bool HasKey(const std::string& key, const nlohmann::json& data) {
  return data.contains(key);
}

inline std::optional<std::string> GetString(const std::string& key) {
  const auto& data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  return data[key].get<std::string>();
}

inline std::vector<std::string> GetStringList(const std::string& key) {
  std::vector<std::string> result;
  const auto& data = GetJson();
  if (!HasKey(key, data)) return {};
  for (const auto& item : data[key]) {
    result.push_back(item.get<std::string>());
  }
  return result;
}

inline std::vector<std::string> GetStringListLower(const std::string& key) {
  std::vector<std::string> result = GetStringList(key);
  for (auto& str : result) {
    std::transform(str.begin(), str.end(), str.begin(),
                   [](unsigned char c) { return std::tolower(c); });
  }
  return result;
}

template <typename T>
inline std::optional<T> GetUintImpl(const std::string& key) {
  const auto& data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  if (data[key].is_number_unsigned()) return data[key].get<T>();
  printf_stderr("ERROR: Value for key '%s' is not an unsigned integer\n",
                key.c_str());
  return std::nullopt;
}

inline std::optional<uint64_t> GetUint64(const std::string& key) {
  return GetUintImpl<uint64_t>(key);
}

inline std::optional<uint32_t> GetUint32(const std::string& key) {
  return GetUintImpl<uint32_t>(key);
}

inline std::optional<int32_t> GetInt32(const std::string& key) {
  const auto& data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  if (data[key].is_number_integer()) return data[key].get<int32_t>();
  printf_stderr("ERROR: Value for key '%s' is not an integer\n", key.c_str());
  return std::nullopt;
}

inline std::optional<double> GetDouble(const std::string& key) {
  const auto& data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  if (data[key].is_number_float()) return data[key].get<double>();
  if (data[key].is_number_unsigned() || data[key].is_number_integer())
    return static_cast<double>(data[key].get<int64_t>());
  printf_stderr("ERROR: Value for key '%s' is not a double\n", key.c_str());
  return std::nullopt;
}

inline std::optional<bool> GetBool(const std::string& key) {
  const auto& data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  if (data[key].is_boolean()) return data[key].get<bool>();
  printf_stderr("ERROR: Value for key '%s' is not a boolean\n", key.c_str());
  return std::nullopt;
}

inline bool CheckBool(const std::string& key) {
  return GetBool(key).value_or(false);
}

inline std::optional<std::array<uint32_t, 4>> GetRect(
    const std::string& left, const std::string& top, const std::string& width,
    const std::string& height) {
  std::array<std::optional<uint32_t>, 4> values = {
      GetUint32(left).value_or(0), GetUint32(top).value_or(0), GetUint32(width),
      GetUint32(height)};

  if (!values[2].has_value() || !values[3].has_value()) {
    if (values[2].has_value() ^ values[3].has_value())
      printf_stderr(
          "Both %s and %s must be provided. Using default behavior.\n",
          height.c_str(), width.c_str());
    return std::nullopt;
  }

  std::array<uint32_t, 4> result;
  std::transform(values.begin(), values.end(), result.begin(),
                 [](const auto& value) { return value.value(); });

  return result;
}

inline std::optional<std::array<int32_t, 4>> GetInt32Rect(
    const std::string& left, const std::string& top, const std::string& width,
    const std::string& height) {
  if (auto optValue = GetRect(left, top, width, height)) {
    std::array<int32_t, 4> result;
    std::transform(optValue->begin(), optValue->end(), result.begin(),
                   [](const auto& val) { return static_cast<int32_t>(val); });
    return result;
  }
  return std::nullopt;
}

// Helpers for WebGL

inline std::optional<nlohmann::json> GetNested(const std::string& domain,
                                               std::string keyStr) {
  auto data = GetJson();
  if (!data.contains(domain)) return std::nullopt;

  if (!data[domain].contains(keyStr)) return std::nullopt;

  return data[domain][keyStr];
}

template <typename T>
inline std::optional<T> GetAttribute(const std::string attrib, bool isWebGL2) {
  auto value = MaskConfig::GetNested(
      isWebGL2 ? "webGl2:contextAttributes" : "webGl:contextAttributes",
      attrib);
  if (!value) return std::nullopt;
  return value.value().get<T>();
}

inline std::optional<
    std::variant<int64_t, bool, double, std::string, std::nullptr_t>>
GLParam(uint32_t pname, bool isWebGL2) {
  auto value =
      MaskConfig::GetNested(isWebGL2 ? "webGl2:parameters" : "webGl:parameters",
                            std::to_string(pname));
  if (!value) return std::nullopt;
  auto data = value.value();
  if (data.is_null()) return std::nullptr_t();
  if (data.is_number_integer()) return data.get<int64_t>();
  if (data.is_boolean()) return data.get<bool>();
  if (data.is_number_float()) return data.get<double>();
  if (data.is_string()) return data.get<std::string>();
  return std::nullopt;
}

template <typename T>
inline T MParamGL(uint32_t pname, T defaultValue, bool isWebGL2) {
  if (auto value = MaskConfig::GetNested(
          isWebGL2 ? "webGl2:parameters" : "webGl:parameters",
          std::to_string(pname));
      value.has_value()) {
    return value.value().get<T>();
  }
  return defaultValue;
}

template <typename T>
inline std::vector<T> MParamGLVector(uint32_t pname,
                                     std::vector<T> defaultValue,
                                     bool isWebGL2) {
  if (auto value = MaskConfig::GetNested(
          isWebGL2 ? "webGl2:parameters" : "webGl:parameters",
          std::to_string(pname));
      value.has_value()) {
    if (value.value().is_array()) {
      std::array<T, 4UL> result = value.value().get<std::array<T, 4UL>>();
      return std::vector<T>(result.begin(), result.end());
    }
  }
  return defaultValue;
}

inline std::optional<std::array<int32_t, 3UL>> MShaderData(
    uint32_t shaderType, uint32_t precisionType, bool isWebGL2) {
  std::string valueName =
      std::to_string(shaderType) + "," + std::to_string(precisionType);
  if (auto value =
          MaskConfig::GetNested(isWebGL2 ? "webGl2:shaderPrecisionFormats"
                                         : "webGl:shaderPrecisionFormats",
                                valueName)) {
    // Convert {rangeMin: int, rangeMax: int, precision: int} to array
    auto data = value.value();
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
  auto data = GetJson();
  if (!data.contains("voices") || !data["voices"].is_array()) {
    return std::nullopt;
  }

  std::vector<std::tuple<std::string, std::string, std::string, bool, bool>>
      voices;
  for (const auto& voice : data["voices"]) {
    // Check if voice has all required fields
    if (!voice.contains("lang") || !voice.contains("name") ||
        !voice.contains("voiceUri") || !voice.contains("isDefault") ||
        !voice.contains("isLocalService")) {
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