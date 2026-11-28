_Static_assert(sizeof(struct hakios_sta_join)==144, "station ABI retained");
_Static_assert(offsetof(struct hakios_sta_join,security)==40, "security offset retained");
_Static_assert(offsetof(struct hakios_sta_join,pmk)==44, "PMK offset retained");
_Static_assert(offsetof(struct hakios_sta_join,passphrase_length)==140, "credential offset retained");

static struct apple80211_assoc request(unsigned auth, unsigned group, unsigned pair, unsigned caps)
{
    struct apple80211_assoc a={0};
    a.version=a.key_version=1; a.mode=2; a.auth_lower=1; a.auth_upper=(uint16_t)auth;
    a.ssid_length=4;memset(a.ssid,0xa1,4);memset(a.bssid,0xb2,6);
    if(!auth)return a;
    a.key_cipher=CIPHER_PASSPHRASE;a.key_length=8;memset(a.key,0xc3,8);
    const uint8_t rsn[]={48,20,1,0,0,15,172,4,1,0,0,15,172,4,1,0,0,15,172,2,0,0};
    const uint8_t wpa[]={221,22,0,80,242,1,1,0,0,80,242,2,1,0,0,80,242,2,1,0,0,80,242,2};
    bool legacy=auth==2;
    memcpy(a.rsn,legacy?wpa:rsn,legacy?sizeof(wpa):sizeof(rsn));
    a.rsn_length=legacy?sizeof(wpa):sizeof(rsn);
    a.rsn[legacy?11:7]=(uint8_t)group;a.rsn[legacy?17:13]=(uint8_t)pair;
    if(!legacy){a.rsn[19]=auth==4096?8:2;a.rsn[20]=(uint8_t)caps;}
    return a;
}

static void check_request(struct apple80211_assoc *a, int expected, int security,
                          unsigned pair,unsigned group,unsigned pmf)
{
    assert(join_security(a)==expected);
    for(unsigned i=0;i<2;i++)assert(!allocations[i].address);
    memset(allocations,0,sizeof(allocations));memset(&captured,0,sizeof(captured));
    alloc_calls=alloc_fail=free_calls=wipe_calls=copy_calls=native_calls=lock_calls=0;
    copy_error=native_error=0;copied_bytes=0;locked=false;join_result=21;
    struct apple80211req req={.req_type=20,.req_len=sizeof(*a),.req_data=(user_addr_t)a};
    char said[512]={0};assert(set_join(&req,said,sizeof(said))==expected);
    assert(!locked&&free_calls==2&&wipe_calls==2);
    assert(native_calls==(unsigned)(expected==0));
    if(!expected){
        assert(captured.security==security&&captured.pairwise_cipher==pair&&captured.group_cipher==group&&captured.management_protection==pmf);
        assert(captured.ssid_length==a->ssid_length&&!memcmp(captured.ssid,a->ssid,a->ssid_length));
        if(security==HAKIOS_STA_OPEN){assert_zero(captured.pmk,32);assert_zero(captured.passphrase,64);assert(!captured.passphrase_length);}
        else if(a->key_cipher==CIPHER_PMK){assert(!memcmp(captured.pmk,a->key,32));assert(!captured.passphrase_length);}
        else {assert(captured.passphrase_length==a->key_length&&!memcmp(captured.passphrase,a->key,a->key_length));assert_zero(captured.pmk,32);}
    }
    for(size_t i=0;i<strlen(said);i++)assert((unsigned char)said[i]<128);
    memset(&captured,0,sizeof(captured));checks++;
}

int main(void)
{
    struct apple80211_assoc a=request(0,0,0,0);
    check_request(&a,0,HAKIOS_STA_OPEN,0,0,0);
    a.key_version=0;check_request(&a,0,HAKIOS_STA_OPEN,0,0,0);
    a.key_length=1;check_request(&a,EOPNOTSUPP,0,0,0,0);
    for(unsigned auth=2;auth<=8;auth+=6)for(unsigned group=2;group<=4;group+=2)for(unsigned pair=2;pair<=4;pair+=2){
        a=request(auth,group,pair,0);int mode=auth==2?HAKIOS_STA_WPA_PSK:HAKIOS_STA_WPA2_PSK;
        check_request(&a,0,mode,pair,group,0);
        a.key_cipher=CIPHER_PMK;a.key_length=32;memset(a.key,0xd4,32);check_request(&a,0,mode,pair,group,0);
        a.rsn_length=0;check_request(&a,0,mode,0,0,0);
    }
    a=request(8,4,4,0);a.auth_upper=10;check_request(&a,0,HAKIOS_STA_WPA2_PSK,4,4,0);
    a=request(2,2,2,0);a.auth_upper=10;check_request(&a,0,HAKIOS_STA_WPA_PSK,2,2,0);
    a.rsn_length=0;check_request(&a,0,HAKIOS_STA_WPA_AUTO,0,0,0);
    for(unsigned caps=0;caps<256;caps++){
        a=request(4096,4,4,caps);check_request(&a,(caps&128)?0:EOPNOTSUPP,HAKIOS_STA_WPA3_SAE,4,4,caps&192);
        a=request(8,4,4,caps);check_request(&a,(caps&64)&&!(caps&128)?EOPNOTSUPP:0,HAKIOS_STA_WPA2_PSK,4,4,caps&192);
    }
    a=request(8,4,4,128);a.rsn_length=26;a.rsn[1]=24;a.rsn[14]=2;
    memcpy(a.rsn+20,"\x00\x0f\xac\x08\x80\x00",6);
    check_request(&a,0,HAKIOS_STA_WPA2_PSK,4,4,128);
    a.auth_upper=4096;check_request(&a,0,HAKIOS_STA_WPA3_SAE,4,4,128);
    a.rsn_length=0;check_request(&a,EOPNOTSUPP,0,0,0,0);
    a=request(4096,4,4,128);a.key_cipher=CIPHER_PMK;a.key_length=32;check_request(&a,EOPNOTSUPP,0,0,0,0);
    a=request(8,2,4,128);check_request(&a,0,HAKIOS_STA_WPA2_PSK,4,2,128);
    a=request(2,2,2,0);a.auth_upper=8;check_request(&a,EOPNOTSUPP,0,0,0,0);
    a=request(8,4,4,0);a.auth_upper=2;check_request(&a,EOPNOTSUPP,0,0,0,0);
    a=request(8,4,4,0);a.auth_upper=4;check_request(&a,EOPNOTSUPP,0,0,0,0);
    a=request(8,4,4,0);a.rsn[19]=1;check_request(&a,EOPNOTSUPP,0,0,0,0);
    a=request(8,4,4,0);a.rsn[8]=255;check_request(&a,EINVAL,0,0,0,0);
    for(unsigned n=1;n<20;n++){a=request(8,4,4,0);a.rsn_length=n;a.rsn[1]=n>=2?n-2:0;assert(join_security(&a)!=0);checks++;}
    a=request(8,4,4,0);a.rsn_length=65535;check_request(&a,EINVAL,0,0,0,0);
    a=request(8,4,4,192);a.auth_upper=1024;a.rsn[19]=6;
    check_request(&a,0,HAKIOS_STA_WPA2_SHA256,4,4,192);
    a.key_cipher=CIPHER_PMK;a.key_length=32;check_request(&a,0,HAKIOS_STA_WPA2_SHA256,4,4,192);
    a.rsn[19]=2;check_request(&a,EOPNOTSUPP,0,0,0,0);
    a.rsn[19]=6;a.rsn[20]=0;check_request(&a,0,HAKIOS_STA_WPA2_SHA256,4,4,0);
    a=request(8,2,2,128);check_request(&a,0,HAKIOS_STA_WPA2_PSK,2,2,128);
    a.rsn[20]=192;check_request(&a,EOPNOTSUPP,0,0,0,0);
    a=request(8,4,4,0);a.auth_upper=1024;a.rsn[19]=6;check_request(&a,0,HAKIOS_STA_WPA2_SHA256,4,4,0);
    a.rsn[20]=64;check_request(&a,EOPNOTSUPP,0,0,0,0);
    printf("PASS WIFI374 actual native selection/ABI/credential cleanup checks=%u\n",checks);
    return 0;
}
