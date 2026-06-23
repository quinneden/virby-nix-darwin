package socketactivation

/*
#include <launch.h>
#include <stdlib.h>
*/
import "C"
import (
	"fmt"
	"net"
	"os"
	"syscall"
	"unsafe"
)

type SocketActivation struct {
	debug bool
	port  int
}

func NewSocketActivation(debug bool, port int) *SocketActivation {
	return &SocketActivation{
		debug: debug,
		port:  port,
	}
}

func (a *SocketActivation) callLaunchActivateSocket(socketName string) []int {
	cSocketName := C.CString(socketName)
	defer C.free(unsafe.Pointer(cSocketName))

	var fds *C.int
	var count C.size_t

	result := C.launch_activate_socket(cSocketName, &fds, &count)
	if result != 0 || count == 0 {
		return nil
	}

	n := int(count)
	fdSlice := (*[1 << 20]C.int)(unsafe.Pointer(fds))[:n:n]

	slice := make([]int, n)
	for i, fd := range fdSlice {
		slice[i] = int(fd)
	}

	return slice
}

func (a *SocketActivation) inspectSocketFD(fd int) (net.Listener, error) {
	sock := os.NewFile(uintptr(fd), "socket")
	ln, err := net.FileListener(sock)
	sock.Close()

	if err != nil {
		return nil, fmt.Errorf("failed to create listener: %w", err)
	}

	return ln, nil
}

func (a *SocketActivation) listenerMatchesPort(ln net.Listener) bool {
	addr, ok := ln.Addr().(*net.TCPAddr)
	if !ok {
		return false
	}

	return addr.Port == a.port
}

func (a *SocketActivation) processLaunchdSockets(fds []int) (net.Listener, error) {
	for _, fd := range fds {
		ln, err := a.inspectSocketFD(fd)
		if err != nil {
			continue
		}

		if a.listenerMatchesPort(ln) {
			return ln, nil
		}

		ln.Close()
	}

	return nil, fmt.Errorf("no activation socket found on port %d", a.port)
}

func (a *SocketActivation) fallbackSocketScan() (net.Listener, error) {
	for fd := 3; fd < 256; fd++ {
		var st syscall.Stat_t

		if err := syscall.Fstat(fd, &st); err != nil {
			continue
		}
		if st.Mode&syscall.S_IFSOCK == 0 {
			continue
		}

		ln, err := a.inspectSocketFD(fd)
		if err != nil {
			continue
		}

		if a.listenerMatchesPort(ln) {
			return ln, nil
		}

		ln.Close()
	}

	return nil, fmt.Errorf("no activation socket found on port %d", a.port)
}

func (a *SocketActivation) GetActivationSocket() (net.Listener, error) {
	fds := a.callLaunchActivateSocket("Listener")
	if len(fds) > 0 {
		return a.processLaunchdSockets(fds)
	}
	return a.fallbackSocketScan()
}
