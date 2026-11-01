//go:build !linux && !windows

package inventory

import "errors"

func CollectInstalledPackages() (PackageSnapshot, error) {
	return PackageSnapshot{}, errors.New("native installed-package collection is currently supported on Windows and Linux")
}
