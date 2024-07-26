/*
Helper to extract values from the Mask Config JSON file.
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
#include <stdlib.h>
#include <stdio.h>

namespace MaskConfig {

inline const nlohmann::json& GetJson() {
  static const nlohmann::json jsonConfig = []() {
    const char* jsonString = getenv("CAMOU_CONFIG");
    if (!jsonString) return nlohmann::json{};
    // Validate
    if (!nlohmann::json::accept(jsonString)) {
      printf_stderr("ERROR: Invalid JSON passed to CAMOU_CONFIG!\n");
      return nlohmann::json{};
    }
    nlohmann::json result = nlohmann::json::parse(jsonString);
    return result;
  }();
  return jsonConfig;
}

inline bool HasKey(const std::string& key, nlohmann::json& data) {
  if (!data.contains(key)) {
    // printf_stderr("WARNING: Key not found: %s\n", key.c_str());
    return false;
  }
  return true;
}

inline std::optional<std::string> GetString(const std::string& key) {
  // printf_stderr("GetString: %s\n", key.c_str());
  auto data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  return std::make_optional(data[key].get<std::string>());
}

inline std::vector<std::string> GetStringList(const std::string& key) {
  std::vector<std::string> result;

  auto data = GetJson();
  if (!HasKey(key, data)) return {};
  // Build vector
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
  auto data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  if (data[key].is_number_unsigned())
    return std::make_optional(data[key].get<T>());
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
  auto data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  if (data[key].is_number_integer())
    return std::make_optional(data[key].get<int32_t>());
  printf_stderr("ERROR: Value for key '%s' is not an integer\n", key.c_str());
  return std::nullopt;
}

inline std::optional<double> GetDouble(const std::string& key) {
  auto data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  if (data[key].is_number_float())
    return std::make_optional(data[key].get<double>());
  if (data[key].is_number_unsigned() || data[key].is_number_integer())
    return std::make_optional(static_cast<double>(data[key].get<int64_t>()));
  printf_stderr("ERROR: Value for key '%s' is not a double\n", key.c_str());
  return std::nullopt;
}

inline std::optional<bool> GetBool(const std::string& key) {
  auto data = GetJson();
  if (!HasKey(key, data)) return std::nullopt;
  if (data[key].is_boolean()) return std::make_optional(data[key].get<bool>());
  printf_stderr("ERROR: Value for key '%s' is not a boolean\n", key.c_str());
  return std::nullopt;
}

inline std::optional<std::array<uint32_t, 4>> GetRect(
    const std::string& top, const std::string& left, const std::string& height,
    const std::string& width) {
  // Make top and left default to 0
  std::array<std::optional<uint32_t>, 4> values = {
      GetUint32(top).value_or(0), GetUint32(left).value_or(0),
      GetUint32(height), GetUint32(width)};

  // If height or width is std::nullopt, return std::nullopt
  if (!values[2].has_value() || !values[3].has_value()) {
    if (values[2].has_value() ^ values[3].has_value())
      printf_stderr(
          "Both %s and %s must be provided. Using default "
          "behavior.\n",
          height.c_str(), width.c_str());
    return std::nullopt;
  }

  // Convert std::optional<uint32_t> to uint32_t
  std::array<uint32_t, 4> result;
  std::transform(values.begin(), values.end(), result.begin(),
                 [](const auto& value) { return value.value(); });

  return result;
}

inline std::optional<std::array<int32_t, 4>> GetInt32Rect(
    const std::string& top, const std::string& left, const std::string& height,
    const std::string& width) {
  // Calls GetRect but casts to int32_t
  if (auto optValue = GetRect(top, left, height, width)) {
    std::array<int32_t, 4> result;
    std::transform(optValue->begin(), optValue->end(), result.begin(),
                   [](const auto& val) { return static_cast<int32_t>(val); });
    return result;
  }
  return std::nullopt;
}

}  // namespace MaskConfig