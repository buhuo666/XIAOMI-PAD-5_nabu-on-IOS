// A bounded read-only QRTR service discovery probe, run as Android root.
#include <sys/socket.h>
#include <linux/qrtr.h>
#include <unistd.h>
#include <poll.h>
#include <errno.h>
#include <stdio.h>
#include <stdint.h>
#include <time.h>
#include <string.h>

static uint64_t milliseconds() {
    timespec t{}; clock_gettime(CLOCK_MONOTONIC, &t);
    return uint64_t(t.tv_sec)*1000+t.tv_nsec/1000000;
}

int main() {
    setvbuf(stdout,nullptr,_IOLBF,0);
    int fd=socket(AF_QIPCRTR,SOCK_DGRAM|SOCK_CLOEXEC,0);
    if(fd<0){perror("socket QRTR");return 1;}
    sockaddr_qrtr local{}; socklen_t len=sizeof(local);
    if(getsockname(fd,reinterpret_cast<sockaddr*>(&local),&len)){perror("getsockname");close(fd);return 2;}
    printf("{\"kind\":\"local\",\"node\":%u,\"port\":%u}\n",local.sq_node,local.sq_port);
    sockaddr_qrtr ns=local; ns.sq_port=QRTR_PORT_CTRL;
    qrtr_ctrl_pkt lookup{}; lookup.cmd=QRTR_TYPE_NEW_LOOKUP;
    lookup.server.service=400;
    if(sendto(fd,&lookup,sizeof(lookup),0,reinterpret_cast<sockaddr*>(&ns),sizeof(ns))<0){perror("lookup");close(fd);return 3;}
    const uint64_t end=milliseconds()+3000;
    unsigned matches=0;
    while(milliseconds()<end){
        pollfd poller{fd,POLLIN,0};
        if(poll(&poller,1,100)<=0)continue;
        uint8_t data[4096];sockaddr_qrtr from{};len=sizeof(from);
        ssize_t n=recvfrom(fd,data,sizeof(data),0,reinterpret_cast<sockaddr*>(&from),&len);
        if(n<0){perror("receive");break;}
        printf("{\"kind\":\"rx\",\"node\":%u,\"port\":%u,\"hex\":\"",from.sq_node,from.sq_port);
        for(ssize_t i=0;i<n;++i)printf("%02x",data[i]);puts("\"}");
        if(n>=ssize_t(sizeof(qrtr_ctrl_pkt)) && from.sq_port==QRTR_PORT_CTRL){
            qrtr_ctrl_pkt packet;memcpy(&packet,data,sizeof(packet));
            if(packet.cmd==QRTR_TYPE_NEW_SERVER && packet.server.service==400){
                ++matches;
                printf("{\"kind\":\"ssc_service\",\"node\":%u,\"port\":%u,\"instance\":%u}\n",packet.server.node,packet.server.port,packet.server.instance);
            }
        }
    }
    close(fd);
    printf("{\"kind\":\"complete\",\"service_count\":%u}\n",matches);
    return 0;
}
