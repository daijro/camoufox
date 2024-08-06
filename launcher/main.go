package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

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
	runCamoufox(execName, remainingArgs)
}

func parseArgs(args []string) (string, []string) {
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
	for _, font := range fontsByOS[userAgentOS] {
		if !existingFonts[font] {
			fonts = append(fonts, font)
		}
	}
	configMap["fonts"] = fonts
}

func setEnvironmentVariables(configMap map[string]interface{}, userAgentOS string) {
	updatedConfigData, err := json.Marshal(configMap)
	if err != nil {
		fmt.Printf("Error updating config: %v\n", err)
		os.Exit(1)
	}

	os.Setenv("CAMOU_CONFIG", string(updatedConfigData))
	if normalizeOS(runtime.GOOS) == "linux" {
		fontconfigPath := filepath.Join("fontconfig", userAgentOS)
		os.Setenv("FONTCONFIG_PATH", fontconfigPath)
	}
}

func getExecutableName() string {
	switch normalizeOS(runtime.GOOS) {
	case "linux":
		return "./camoufox-bin"
	case "macos":
		return "./Camoufox.app"
	case "windows":
		return "camoufox.exe"
	default:
		// This should never be reached due to the check in normalizeOS
		return ""
	}
}

func runCamoufox(execName string, args []string) {
	cmd := exec.Command(execName, args...)

	// Create pipes for stdout and stderr
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		fmt.Printf("Error creating stdout pipe: %v\n", err)
		os.Exit(1)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		fmt.Printf("Error creating stderr pipe: %v\n", err)
		os.Exit(1)
	}

	// Start the command
	if err := cmd.Start(); err != nil {
		fmt.Printf("Error starting %s: %v\n", execName, err)
		os.Exit(1)
	}

	// Create a channel to signal when we're done copying output
	done := make(chan bool)

	// Copy stdout and stderr to the console
	go func() {
		io.Copy(os.Stdout, stdout)
		done <- true
	}()
	go func() {
		io.Copy(os.Stderr, stderr)
		done <- true
	}()

	// Wait for both stdout and stderr to finish
	<-done
	<-done

	// Wait for the command to finish
	if err := cmd.Wait(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			os.Exit(exitErr.ExitCode())
		} else {
			fmt.Printf("Error running %s: %v\n", execName, err)
			os.Exit(1)
		}
	}
}
