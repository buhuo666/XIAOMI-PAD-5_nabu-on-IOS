/* Probe the unmodified 20F66 lockdownd through its launchd TCP socket.
 * Read-only requests: no Pair, ValidatePair, activation or trust changes.
 */
#include <stdint.h>
#include <stddef.h>
extern int printf(const char *, ...) __attribute__((format(printf,1,2)));
extern int snprintf(char *, size_t, const char *, ...) __attribute__((format(printf,3,4)));
extern int fflush(void *);
extern void *malloc(size_t);
extern void free(void *);
extern size_t strlen(const char *);
extern unsigned sleep(unsigned);
extern unsigned alarm(unsigned);
extern int socket(int,int,int), connect(int,const void *,unsigned), close(int);
extern long read(int,void *,size_t), write(int,const void *,size_t);
extern int setsockopt(int,int,int,const void *,unsigned);
extern int *__error(void);

static uint16_t be16(uint16_t n) { return (uint16_t)((n<<8)|(n>>8)); }
static uint32_t be32(uint32_t n) { return __builtin_bswap32(n); }
static int transfer(int fd, void *buffer, unsigned size, int sending)
{
    unsigned at=0;
    while (at<size) {
        long n=sending ? write(fd,(char *)buffer+at,size-at) : read(fd,(char *)buffer+at,size-at);
        if (n<=0) return 0;
        at+=(unsigned)n;
    }
    return 1;
}

static void query(const char *request, const char *key)
{
    int fd=socket(2,1,0);
    struct { uint8_t length,family; uint16_t port; uint32_t address; uint8_t zero[8]; }
        address={16,2,be16(62078),be32(0x7f000001),{0}};
    struct { long sec; int32_t usec; } timeout={3,0};
    if (fd<0) { printf("NABU LOCKDOWN: socket errno=%d\n",*__error()); return; }
    setsockopt(fd,0xffff,0x1006,&timeout,sizeof(timeout));
    setsockopt(fd,0xffff,0x1005,&timeout,sizeof(timeout));
    if (connect(fd,&address,sizeof(address))) {
        printf("NABU LOCKDOWN: connect request=%s key=%s errno=%d\n",request,key,*__error());
        close(fd); return;
    }
    char xml[1024],entry[256]="";
    if (*key) snprintf(entry,sizeof(entry),"<key>Key</key><string>%s</string>",key);
    int length=snprintf(xml,sizeof(xml),"<?xml version=\"1.0\"?><plist version=\"1.0\"><dict>"
        "<key>Label</key><string>NabuNativeUSBProbe</string><key>Request</key><string>%s</string>%s</dict></plist>",request,entry);
    uint32_t frame=be32((uint32_t)length);
    if (!transfer(fd,&frame,4,1) || !transfer(fd,xml,(unsigned)length,1) || !transfer(fd,&frame,4,0)) {
        printf("NABU LOCKDOWN: exchange request=%s key=%s errno=%d\n",request,key,*__error());
        close(fd); return;
    }
    unsigned count=be32(frame);
    unsigned char *reply=malloc(count);
    if (!transfer(fd,reply,count,0)) {
        printf("NABU LOCKDOWN: response-read request=%s key=%s length=%u errno=%d\n",request,key,count,*__error());
    } else {
        printf("NABU LOCKDOWN: RESPONSE request=%s key=%s length=%u\n",request,key,count);
        for (unsigned at=0;at<count;at+=128) {
            char hex[257];unsigned n=count-at<128?count-at:128;
            const char *digits="0123456789abcdef";
            for(unsigned i=0;i<n;i++){hex[i*2]=digits[reply[at+i]>>4];hex[i*2+1]=digits[reply[at+i]&15];}
            hex[n*2]=0;
            printf("NABU LOCKDOWN: DATA offset=%u hex=%s\n",at,hex);
        }
        printf("NABU LOCKDOWN: ENDRESPONSE\n");
    }
    free(reply);close(fd);fflush(0);
}

int main(void)
{
    printf("NABU LOCKDOWN: scheduled after 35 seconds\n");fflush(0);sleep(35);alarm(30);
    query("QueryType","");
    query("GetValue","ProductType");
    query("GetValue","DeviceName");
    query("GetValue","ActivationState");
    printf("NABU LOCKDOWN: COMPLETE\n");fflush(0);
    return 0;
}
