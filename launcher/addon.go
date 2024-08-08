package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
)

func getDebugPort(args *[]string) int {
	debugPort := parseArgs("-start-debugger-server", "", args, false)

	var debugPortInt int
	var err error
	if debugPort == "" {
		// Create new debugger server port
		debugPortInt = getOpenPort()
		// Add -start-debugger-server {debugPort} to args
		*args = append(*args, "-start-debugger-server", strconv.Itoa(debugPortInt))
	} else {
		debugPortInt, err = strconv.Atoi(debugPort)
		if err != nil {
			fmt.Printf("Error parsing debug port. Must be an integer: %v\n", err)
			os.Exit(1)
		}
	}
	return debugPortInt
}

func confirmPaths(paths []string) {
	// Confirm paths are valid
	for _, path := range paths {
		if _, err := os.Stat(path); err != nil {
			fmt.Printf("Error: %s is not a valid addon path.\n", path)
			os.Exit(1)
		}
	}
}

func getOpenPort() int {
	// Generate an open port
	ln, err := net.Listen("tcp", ":0") // listen on a random port
	if err != nil {
		return 0
	}
	defer ln.Close()

	addr := ln.Addr().(*net.TCPAddr) // type assert to *net.TCPAddr to get the Port
	return addr.Port
}

// Firefox addon loader
// Ported from this Nodejs implementation:
// https://github.com/microsoft/playwright/issues/7297#issuecomment-1211763085
func loadFirefoxAddon(port int, addonPath string) bool {
	conn, err := net.Dial("tcp", fmt.Sprintf("%s:%d", "localhost", port))
	if err != nil {
		return false
	}
	defer conn.Close()

	success := false

	send := func(data map[string]string) error {
		jsonData, err := json.Marshal(data)
		if err != nil {
			return err
		}
		_, err = fmt.Fprintf(conn, "%d:%s", len(jsonData), jsonData)
		return err
	}

	err = send(map[string]string{
		"to":   "root",
		"type": "getRoot",
	})
	if err != nil {
		return false
	}

	onMessage := func(message map[string]interface{}) bool {
		if addonsActor, ok := message["addonsActor"].(string); ok {
			err := send(map[string]string{
				"to":        addonsActor,
				"type":      "installTemporaryAddon",
				"addonPath": addonPath,
			})
			if err != nil {
				return true
			}
		}

		if _, ok := message["addon"]; ok {
			success = true
			return true
		}

		if _, ok := message["error"]; ok {
			return true
		}

		return false
	}

	reader := bufio.NewReader(conn)
	for {
		lengthStr, err := reader.ReadString(':')
		if err != nil {
			break
		}
		length, err := strconv.Atoi(strings.TrimSuffix(lengthStr, ":"))
		if err != nil {
			break
		}

		jsonData := make([]byte, length)
		_, err = reader.Read(jsonData)
		if err != nil {
			break
		}

		var message map[string]interface{}
		err = json.Unmarshal(jsonData, &message)
		if err != nil {
			break
		}

		if onMessage(message) {
			break
		}
	}

	return success
}
