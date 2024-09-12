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
	args := os.Args[1:]

	configPath := parseArgs("--config", "{}", &args, true)
	addons := parseArgs("--addons", "[]", &args, true)
	excludeAddons := parseArgs("--exclude-addons", "[]", &args, true)
	stderrPath := parseArgs("--stderr", "", &args, true)

	//*** PARSE CONFIG ***//

	// Read and parse the config file
	var configMap map[string]interface{}
	parseJson(configPath, &configMap)
	validateConfig(configMap)

	// Add "debug: True" to the config
	if stderrPath != "" {
		configMap["debug"] = true
	}

	//*** PARSE ADDONS ***//

	// If addons are passed, handle them
	var addonsList []string
	parseJson(addons, &addonsList)

	// Confirm addon paths are valid
	confirmPaths(addonsList)

	// Add the default addons, excluding the ones specified in --exclude-addons
	var excludeAddonsList []string
	parseJson(excludeAddons, &excludeAddonsList)

	addDefaultAddons(excludeAddonsList, &addonsList)

	//*** FONTS ***//

	// Determine the target OS
	userAgentOS := determineUserAgentOS(configMap)
	// Add OS specific fonts
	updateFonts(configMap, userAgentOS)

	//*** LAUNCH ***//

	setEnvironmentVariables(configMap, userAgentOS)

	// Run the Camoufox executable
	execName := getExecutableName()
	if err := setExecutablePermissions(execName); err != nil {
		fmt.Printf("Error setting executable permissions: %v\n", err)
		os.Exit(1)
	}
	runCamoufox(execName, args, addonsList, stderrPath)
}

// Returns the absolute path relative to the launcher
func getPath(path string) string {
	execPath, err := os.Executable()
	if err != nil {
		fmt.Printf("Error getting executable path: %v\n", err)
		os.Exit(1)
	}
	execDir := filepath.Dir(execPath)

	addonPath := filepath.Join(execDir, path)
	return addonPath
}

// Parses & removes an argument from the args list
func parseArgs(param string, defaultValue string, args *[]string, removeFromArgs bool) string {
	for i := 0; i < len(*args); i++ {
		if (*args)[i] != param {
			continue
		}
		if i+1 < len(*args) {
			value := (*args)[i+1]
			if removeFromArgs {
				*args = append((*args)[:i], (*args)[i+2:]...)
			}
			return value
		}
		fmt.Printf("Error: %s flag requires a value\n", param)
		os.Exit(1)
	}
	return defaultValue
}

// fileExists checks if a file exists
func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// Parses a JSON string or file into a map
func parseJson(argv string, target interface{}) {
	// Unmarshal the config input into a map
	var data []byte
	var err error

	// Check if the input is a file path or inline JSON
	if fileExists(argv) {
		data, err = os.ReadFile(argv)
		if err != nil {
			fmt.Printf("Error reading JSON file: %v\n", err)
			os.Exit(1)
		}
	} else {
		// Assume it's inline JSON
		data = []byte(argv)
	}

	if err := json.Unmarshal(data, target); err != nil {
		fmt.Printf("Invalid JSON: %v\n", err)
		os.Exit(1)
	}
}

// Determines the target OS from the user agent string if provided
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

// Get the OS name as {macos, windows, linux}
func normalizeOS(osName string) string {
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

// Add fonts associated with the OS to the config map
func updateFonts(configMap map[string]interface{}, userAgentOS string) {
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

// Update the config map with the fonts and environment variables
func setEnvironmentVariables(configMap map[string]interface{}, userAgentOS string) {
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
		fontconfigPath := getPath(filepath.Join("fontconfig", userAgentOS))
		os.Setenv("FONTCONFIG_PATH", fontconfigPath)
	}
}
