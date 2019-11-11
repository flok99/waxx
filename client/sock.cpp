#include <netdb.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/types.h>

#include "error.h"

int connect_to(const char *host, const int portnr)
{
	struct addrinfo hints;
	memset(&hints, 0, sizeof(struct addrinfo));
	hints.ai_family = AF_UNSPEC;    // Allow IPv4 or IPv6
	hints.ai_socktype = SOCK_STREAM;
	hints.ai_flags = AI_PASSIVE;    // For wildcard IP address
	hints.ai_protocol = 0;          // Any protocol
	hints.ai_canonname = NULL;
	hints.ai_addr = NULL;
	hints.ai_next = NULL;

	char portnr_str[8];
	snprintf(portnr_str, sizeof portnr_str, "%d", portnr);

	struct addrinfo *result;
	int rc = getaddrinfo(host, portnr_str, &hints, &result);
	if (rc != 0) 
		error_exit(false, "Problem resolving %s: %s\n", host, gai_strerror(rc));

	for(struct addrinfo *rp = result; rp != NULL; rp = rp->ai_next)
	{
		int fd = socket(rp -> ai_family, rp -> ai_socktype, rp -> ai_protocol);
		if (fd == -1)
			continue;

		if (connect(fd, rp -> ai_addr, rp -> ai_addrlen) == 0)
		{
			freeaddrinfo(result);

			return fd;
		}

		close(fd);
	}

	freeaddrinfo(result);

	return -1;
}

void set_nodelay(int fd)
{
	int on = 1;
	if (setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, (char *) &on, sizeof(int)) == -1)
		error_exit(true, "TCP_NODELAY");
}
