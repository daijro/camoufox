package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"unicode/utf8"

	json "github.com/goccy/go-json"
	"github.com/mileusna/useragent"
)

func main() {
	configPath, remainingArgs := parseArgs(os.Args[1:]) // Parse args arguments

	configMap := readAndParseConfig(configPath) // Read and parse the config file

	userAgentOS := determineUserAgentOS(configMap) // Determine the user agent OS

	// OS specific font config
	updateFonts(configMap, userAgentOS)
	setEnvironmentVariables(configMap, userAgentOS)

	// Run the Camoufox executable
	execName := getExecutableName()
	if err := setExecutablePermissions(execName); err != nil {
		fmt.Printf("Error setting executable permissions: %v\n", err)
		os.Exit(1)
	}
	runCamoufox(execName, remainingArgs)
}

func parseArgs(args []string) (string, []string) {
	// Parse the arguments
	var configPath string
	var remainingArgs []string

	for i := 0; i < len(args); i++ {
		if args[i] == "--config" {
			if i+1 < len(args) {
				configPath = args[i+1]
				remainingArgs = append(args[:i], args[i+2:]...)
				break
			} else {
				fmt.Println("Error: --config flag requires a value")
				os.Exit(1)
			}
		}
	}

	// If no config data is provided, fallback to an empty object
	if configPath == "" {
		configPath = "{}"
	}

	return configPath, remainingArgs
}

func readAndParseConfig(configInput string) map[string]interface{} {
	// Unmarshal the config input into a map
	var configData []byte

	// Check if the input is a file path or inline JSON
	if _, err := os.Stat(configInput); err == nil {
		configData, err = os.ReadFile(configInput)
		if err != nil {
			fmt.Printf("Error reading config file: %v\n", err)
			os.Exit(1)
		}
	} else {
		// Assume it's inline JSON
		configData = []byte(configInput)
	}

	var configMap map[string]interface{}
	if err := json.Unmarshal(configData, &configMap); err != nil {
		fmt.Printf("Invalid JSON in config: %v\n", err)
		os.Exit(1)
	}

	return configMap
}

func determineUserAgentOS(configMap map[string]interface{}) string {
	// Determine the OS from the user agent string if provided
	defaultOS := normalizeOS(runtime.GOOS)
	if ua, ok := configMap["navigator.userAgent"].(string); ok {
		parsedUA := useragent.Parse(ua)
		if parsedUA.OS != "" {
			return normalizeOS(parsedUA.OS)
		}
	}
	return defaultOS
}

func normalizeOS(osName string) string {
	// Get the OS name as {macos, windows, linux}
	osName = strings.ToLower(osName)
	switch {
	case osName == "darwin" || strings.Contains(osName, "mac"):
		return "macos"
	case strings.Contains(osName, "win"):
		return "windows"
	default:
		return "linux"
	}
}

func updateFonts(configMap map[string]interface{}, userAgentOS string) {
	// Add fonts associated with the OS to the config map
	fonts, ok := configMap["fonts"].([]interface{})
	if !ok {
		fonts = []interface{}{}
	}
	existingFonts := make(map[string]bool)
	for _, font := range fonts {
		if f, ok := font.(string); ok {
			existingFonts[f] = true
		}
	}
	for _, font := range FontsByOS[userAgentOS] {
		if !existingFonts[font] {
			fonts = append(fonts, font)
		}
	}
	configMap["fonts"] = fonts
}

func setEnvironmentVariables(configMap map[string]interface{}, userAgentOS string) {
	// Update the config map with the fonts and environment variables
	updatedConfigData, err := json.Marshal(configMap)
	if err != nil {
		fmt.Printf("Error updating config: %v\n", err)
		os.Exit(1)
	}

	// Validate utf8
	if !utf8.Valid(updatedConfigData) {
		fmt.Println("Config is not valid UTF-8")
		os.Exit(1)
	}

	// Split the config into chunks of 2047 characters if the OS is Windows,
	// otherwise split into 32767 characters
	var chunkSize int
	if normalizeOS(runtime.GOOS) == "windows" {
		chunkSize = 2047
	} else {
		chunkSize = 32767
	}

	configStr := string(updatedConfigData)
	for i := 0; i < len(configStr); i += chunkSize {
		end := i + chunkSize
		if end > len(configStr) {
			end = len(configStr)
		}
		chunk := configStr[i:end]
		envName := fmt.Sprintf("CAMOU_CONFIG_%d", (i/chunkSize)+1)
		if err := os.Setenv(envName, chunk); err != nil {
			fmt.Printf("Error setting %s: %v\n", envName, err)
			os.Exit(1)
		}
	}

	if normalizeOS(runtime.GOOS) == "linux" {
		fontconfigPath := filepath.Join("fontconfig", userAgentOS)
		os.Setenv("FONTCONFIG_PATH", fontconfigPath)
	}
}
