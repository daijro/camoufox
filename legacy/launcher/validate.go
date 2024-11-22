package main

import (
	"fmt"
	"math"
	"os"
	"reflect"
	"runtime"
)

type Property struct {
	Property string `json:"property"`
	Type     string `json:"type"`
}

func validateConfig(configMap map[string]interface{}) {
	properties := loadProperties()

	// Create a map for quick lookup of property types
	propertyTypes := make(map[string]string)
	for _, prop := range properties {
		propertyTypes[prop.Property] = prop.Type
	}

	for key, value := range configMap {
		expectedType, exists := propertyTypes[key]
		if !exists {
			fmt.Printf("Warning: Unknown property %s in config\n", key)
			continue
		}

		if !validateType(value, expectedType) {
			fmt.Printf("Invalid type for property %s. Expected %s, got %T\n", key, expectedType, value)
			os.Exit(1)
		}
	}
}

func loadProperties() []Property {
	// Get the path to the properties.json file
	var propertiesPath string
	if normalizeOS(runtime.GOOS) == "macos" {
		propertiesPath = getPath("Camoufox.app/Contents/Resources/properties.json")
	} else {
		propertiesPath = getPath("properties.json")
	}
	var properties []Property
	// Parse the JSON file
	parseJson(propertiesPath, &properties)
	return properties
}

func validateType(value interface{}, expectedType string) bool {
	switch expectedType {
	case "str":
		_, ok := value.(string)
		return ok
	case "int":
		v, ok := value.(float64)
		return ok && v == math.Trunc(v)
	case "uint":
		v, ok := value.(float64)
		return ok && v == math.Trunc(v) && v >= 0
	case "double":
		_, ok := value.(float64)
		return ok
	case "bool":
		_, ok := value.(bool)
		return ok
	case "array":
		return reflect.TypeOf(value).Kind() == reflect.Slice
	default:
		return false
	}
}
