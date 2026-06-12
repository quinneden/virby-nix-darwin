package ipdiscovery

import (
	"fmt"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
)

const dhcpdLeasesFilePath = "/var/db/dhcpd_leases"

var leadingZeroRegexp = regexp.MustCompile(`0([A-Fa-f0-9](:|$))`)

type dhcpEntry struct {
	hwAddress  string
	identifier string
	ipAddress  string
	lease      string
	name       string
}

type IPDiscovery struct {
	cachedEntries []dhcpEntry
	cachedMtime   time.Time
	leasesFile    string
	macAddress    string
	mu            sync.Mutex
}

func NewIPDiscovery(macAddress string, leasesFile string) *IPDiscovery {
	if leasesFile == "" {
		leasesFile = dhcpdLeasesFilePath
	}

	return &IPDiscovery{
		leasesFile: leasesFile,
		macAddress: normalizeMac(macAddress),
	}
}

func normalizeMac(mac string) string {
	lower := strings.ToLower(mac)
	return leadingZeroRegexp.ReplaceAllString(lower, "$1")
}

func parseDHCPLeases(content string) []dhcpEntry {
	var entries []dhcpEntry
	var currentEntry *dhcpEntry

	lines := strings.SplitSeq(content, "\n")
	for line := range lines {
		line := strings.TrimSpace(line)
		if line == "{" {
			currentEntry = &dhcpEntry{}
			continue
		} else if line == "}" {
			if currentEntry != nil {
				entries = append(entries, *currentEntry)
				currentEntry = nil
			}
			continue
		}
		if currentEntry == nil {
			continue
		}
		if !strings.Contains(line, "=") {
			continue
		}

		kv := strings.SplitN(line, "=", 2)
		key := strings.TrimSpace(kv[0])
		value := strings.TrimSpace(kv[1])

		switch key {
		case "name":
			currentEntry.name = value
		case "ip_address":
			currentEntry.ipAddress = value
		case "hw_address":
			value = strings.TrimPrefix(value, "1,")
			currentEntry.hwAddress = normalizeMac(value)
		case "identifier":
			currentEntry.identifier = value
		case "lease":
			currentEntry.lease = value
		}
	}

	return entries
}

func (d *IPDiscovery) DiscoverIP() (string, error) {
	d.mu.Lock()
	defer d.mu.Unlock()

	info, err := os.Stat(d.leasesFile)
	if err != nil {
		if os.IsNotExist(err) {
			return "", nil
		} else {
			return "", err
		}
	}

	currentMtime := info.ModTime()
	var entries []dhcpEntry
	if !d.cachedMtime.IsZero() && currentMtime.Equal(d.cachedMtime) {
		entries = d.cachedEntries
	} else {
		content, err := os.ReadFile(d.leasesFile)
		if err != nil {
			return "", fmt.Errorf("could not read file: %w", err)
		}
		entries = parseDHCPLeases(string(content))
		d.cachedEntries = entries
		d.cachedMtime = currentMtime
	}

	for _, entry := range entries {
		if entry.hwAddress == d.macAddress {
			fmt.Printf("found IP %s for MAC %s", entry.ipAddress, d.macAddress)
			return entry.ipAddress, nil
		}
	}

	return "", nil
}
