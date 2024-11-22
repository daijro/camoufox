package main

import (
	"archive/zip"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
)

// Downloads and extracts the default addons
func addDefaultAddons(excludeList []string, addonsList *[]string) {
	// Build a map from DefaultAddons, excluding keys found in excludeAddonsList
	addonsMap := make(map[string]string)
	for name, url := range DefaultAddons {
		if len(excludeList) == 0 || !contains(excludeList, name) {
			addonsMap[name] = url
		}
	}

	// Download if not already downloaded
	maybeDownloadAddons(addonsMap, addonsList)
}

// Downloads and extracts the addon
func downloadAndExtract(url, extractPath string) error {
	// Create a temporary file to store the downloaded zip
	tempFile, err := os.CreateTemp("", "camoufox-addon-*.zip")
	if err != nil {
		return fmt.Errorf("failed to create temp file: %w", err)
	}
	defer os.Remove(tempFile.Name()) // Clean up the temp file when done

	// Download the zip file
	resp, err := http.Get(url)
	if err != nil {
		return fmt.Errorf("failed to download addon: %w", err)
	}
	defer resp.Body.Close()

	// Write the body to the temp file
	_, err = io.Copy(tempFile, resp.Body)
	if err != nil {
		return fmt.Errorf("failed to write addon to temp file: %w", err)
	}

	// Close the file before unzipping
	tempFile.Close()

	// Extract the zip file
	err = unzip(tempFile.Name(), extractPath)
	if err != nil {
		return fmt.Errorf("failed to extract addon: %w", err)
	}

	return nil
}

// Extracts the zip file
func unzip(src, dest string) error {
	r, err := zip.OpenReader(src)
	if err != nil {
		return err
	}
	defer r.Close()

	for _, f := range r.File {
		fpath := filepath.Join(dest, f.Name)

		if f.FileInfo().IsDir() {
			os.MkdirAll(fpath, os.ModePerm)
			continue
		}

		if err = os.MkdirAll(filepath.Dir(fpath), os.ModePerm); err != nil {
			return err
		}

		outFile, err := os.OpenFile(fpath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, f.Mode())
		if err != nil {
			return err
		}

		rc, err := f.Open()
		if err != nil {
			outFile.Close()
			return err
		}

		_, err = io.Copy(outFile, rc)
		outFile.Close()
		rc.Close()

		if err != nil {
			return err
		}
	}
	return nil
}

// Checks if a slice contains a string
func contains(slice []string, item string) bool {
	for _, s := range slice {
		if s == item {
			return true
		}
	}
	return false
}

// Returns the absolute path to the target addon location
func getAddonPath(addonName string) string {
	return getPath(filepath.Join("addons", addonName))
}

// Downloads and extracts the addons
func maybeDownloadAddons(addons map[string]string, addonsList *[]string) {
	for addonName, url := range addons {
		// Get the addon path
		addonPath := getAddonPath(addonName)

		// Check if the addon is already extracted
		if _, err := os.Stat(addonPath); !os.IsNotExist(err) {
			// Add the existing addon path to addonsList
			*addonsList = append(*addonsList, addonPath)
			continue
		}

		// Addon doesn't exist, create directory and download
		err := os.MkdirAll(addonPath, 0755)
		if err != nil {
			fmt.Printf("Failed to create directory for %s: %v\n", addonName, err)
			continue
		}

		err = downloadAndExtract(url, addonPath)
		if err != nil {
			fmt.Printf("Failed to download and extract %s: %v\n", addonName, err)
		} else {
			fmt.Printf("Successfully downloaded and extracted %s\n", addonName)
			// Add the new addon directory path to addonsList
			*addonsList = append(*addonsList, addonPath)
		}
	}
}
