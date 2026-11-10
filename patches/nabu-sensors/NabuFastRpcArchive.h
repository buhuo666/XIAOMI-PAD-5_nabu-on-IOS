// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuFastRpcProtocol.h"

namespace NabuFastRpc {
class Archive {
    const uint8_t *data=nullptr;
    uint32_t bytes=0,count=0;
    const uint8_t *entry(unsigned index)const{return data+16+index*264;}
    static bool prefix(const char *path,const char *head){return !strncmp(path,head,strlen(head));}
    static void path_copy(char *out,const char *head,const char *tail){
        size_t a=strlen(head),b=strlen(tail);
        if(a+b>=256){out[0]=0;return;}
        memcpy(out,head,a);memcpy(out+a,tail,b+1);
    }
    static void normalize(const char *path,char *out){
        if(prefix(path,"/dsp/"))path_copy(out,"/vendor/dsp/",path+5);
        else if(prefix(path,"/vendor/lib/rfsa/adsp/"))path_copy(out,"/vendor/dsp/sdsp/",path+strlen("/vendor/lib/rfsa/adsp/"));
        else path_copy(out,"",path);
        size_t n=strlen(out);while(n>1&&out[n-1]=='/')out[--n]=0;
    }
    bool exact(const char *path,const uint8_t *&file,uint32_t &size)const{
        for(unsigned i=0;i<count;++i){const uint8_t *e=entry(i);if(strcmp(reinterpret_cast<const char *>(e),path))continue;
            file=data+u32(e+256);size=u32(e+260);return true;}
        return false;
    }
public:
    bool load(const uint8_t *source,uint32_t length){
        if(length<16||memcmp(source,"NABURPC1",8)||u32(source+12)!=length)return false;
        uint32_t n=u32(source+8);if(n>(length-16)/264)return false;
        for(unsigned i=0;i<n;++i){const uint8_t *e=source+16+i*264;
            if(!memchr(e,0,256)||e[0]!='/'||u32(e+256)<16+n*264||
                u32(e+256)>length||u32(e+260)>length-u32(e+256))return false;}
        data=source;bytes=length;count=n;return true;
    }
    bool open(const char *path,const uint8_t *&file,uint32_t &size)const{
        char actual[256];normalize(path,actual);if(exact(actual,file,size))return true;
        if(path[0]!='/'){
            const char *roots[]={"/vendor/dsp/sdsp/","/vendor/dsp/","/vendor/etc/sensors/"};
            for(const char *root:roots){path_copy(actual,root,path);if(exact(actual,file,size))return true;}
        }
        return false;
    }
    int list(const char *path,unsigned index,char *name,unsigned capacity,uint32_t &size)const{
        char actual[256];normalize(path,actual);size_t n=strlen(actual);bool exists=false;
        if(n==1&&actual[0]=='/')n=0;
        unsigned found=0;
        for(unsigned i=0;i<count;++i){const char *full=reinterpret_cast<const char *>(entry(i));
            if(strncmp(full,actual,n)||full[n]!='/')continue;
            exists=true;const char *child=full+n+1;const char *slash=strchr(child,'/');
            size_t length=slash?size_t(slash-child):strlen(child);bool duplicate=false;
            for(unsigned j=0;j<i;++j){const char *old=reinterpret_cast<const char *>(entry(j));
                if(strncmp(old,actual,n)||old[n]!='/')continue;
                const char *previous=old+n+1;
                if(!strncmp(previous,child,length)&&(previous[length]=='/'||!previous[length])){duplicate=true;break;}}
            if(duplicate||!length)continue;
            if(found++!=index)continue;
            if(length>=capacity)return -1;
            memcpy(name,child,length);name[length]=0;size=slash?0:u32(entry(i)+260);return 1;
        }
        return exists?0:-1;
    }
    unsigned entries()const{return count;}
    unsigned size()const{return bytes;}
};
} // namespace NabuFastRpc
