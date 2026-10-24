// Force-included into every PS5 translation unit of jak-project: fills the gaps between the
// Linux headers the sources assume and the FreeBSD-based PS5 SDK headers.
#pragma once
#ifdef __cplusplus
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#endif

#ifndef TCP_SOCKET_LEVEL
#define TCP_SOCKET_LEVEL IPPROTO_TCP
#endif
#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif
#ifndef SOL_TCP
#define SOL_TCP IPPROTO_TCP
#endif
