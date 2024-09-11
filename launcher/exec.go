package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
)

func getExecutableName() string {
	// Get the executable name based on the OS
	switch normalizeOS(runtime.GOOS) {
	case "linux":
		return getPath("camoufox-bin")
	case "macos":
		return getPath("Camoufox.app")
	case "windows":
		return getPath("camoufox.exe")
	default:
		// This should never be reached due to the check in normalizeOS
		return ""
	}
}

func setExecutablePermissions(execPath string) error {
	// Set executable permissions if needed
	switch normalizeOS(runtime.GOOS) {
	case "macos":
		return filepath.Walk(execPath, func(path string, info os.FileInfo, err error) error {
			if err != nil {
				return err
			}
			return maybeSetPermission(path, 0755)
		})
	case "linux":
		return maybeSetPermission(execPath, 0755)
	}
	return nil
}

func maybeSetPermission(path string, mode os.FileMode) error {
	info, err := os.Stat(path)
	if err != nil {
		return err
	}

	currentMode := info.Mode().Perm()
	if currentMode != mode {
		return os.Chmod(path, mode)
	}
	return nil
}

func filterOutput(r io.Reader, w io.Writer) {
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		line := scanner.Text()
		if !ExclusionRegex.MatchString(line) {
			fmt.Fprintln(w, line)
		}
	}
}

// Run Camoufox
func runCamoufox(execName string, args []string, addonsList []string, stderrPath string) {
	// If addons are specified, get the debug port
	var debugPortInt int
	if len(addonsList) > 0 {
		debugPortInt = getDebugPort(&args)
	}

	// For macOS, use "open" command to launch the app
	if normalizeOS(runtime.GOOS) == "macos" {
		args = append([]string{"-a", execName}, args...)
		execName = "open"
	}

	// Print args
	cmd := exec.Command(execName, args...)

	setProcessGroupID(cmd)

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

	// Set up signal handling
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	if err := cmd.Start(); err != nil {
		fmt.Printf("Error starting %s: %v\n", execName, err)
		os.Exit(1)
	}

	if len(addonsList) > 0 {
		go tryLoadAddons(debugPortInt, addonsList)
	}

	// Channel to signal when the subprocess has finished
	subprocessDone := make(chan struct{})

	// Start a goroutine to handle signals
	go func() {
		select {
		case <-sigChan:
			killProcessGroup(cmd)
		case <-subprocessDone:
			// Subprocess has finished, exit the Go process
			os.Exit(0)
		}
	}()

	done := make(chan bool)

	go func() {
		filterOutput(stdout, os.Stdout)
		done <- true
	}()
	go func() {
		// If stderrPath is not empty, write to the file
		fmt.Printf("Setting stderr to file: %s\n", stderrPath)
		if stderrPath != "" {
			file, err := os.Create(stderrPath)
			if err != nil {
				fmt.Printf("Error creating stderr file: %v\n", err)
				os.Exit(1)
			}
			defer file.Close()
			filterOutput(stderr, file)
		}
		filterOutput(stderr, os.Stderr)
	}()

	<-done
	<-done

	// Wait for the command to finish
	if err := cmd.Wait(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			// If the subprocess exited with an error, use its exit code
			os.Exit(exitErr.ExitCode())
		} else {
			fmt.Printf("Error running %s: %v\n", execName, err)
			os.Exit(1)
		}
	}

	// Signal that the subprocess has finished
	close(subprocessDone)

	// Wait here to allow the signal handling goroutine to exit the process
	select {}
}
