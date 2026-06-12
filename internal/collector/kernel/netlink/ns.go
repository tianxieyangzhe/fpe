//go:build linux

package netlink

import (
	"runtime"

	"github.com/vishvananda/netns"
)

// enterNS switches the current goroutine into the given network namespace.
// name="" means root/current namespace (no-op). Returns a restore function
// that switches back to the original namespace.
func enterNS(name string) (func(), error) {
	runtime.LockOSThread()

	if name == "" {
		return func() { runtime.UnlockOSThread() }, nil
	}

	orig, err := netns.Get()
	if err != nil {
		runtime.UnlockOSThread()
		return nil, err
	}

	target, err := netns.GetFromName(name)
	if err != nil {
		orig.Close()
		runtime.UnlockOSThread()
		return nil, err
	}

	if err := netns.Set(target); err != nil {
		orig.Close()
		target.Close()
		runtime.UnlockOSThread()
		return nil, err
	}

	return func() {
		netns.Set(orig)
		orig.Close()
		target.Close()
		runtime.UnlockOSThread()
	}, nil
}
