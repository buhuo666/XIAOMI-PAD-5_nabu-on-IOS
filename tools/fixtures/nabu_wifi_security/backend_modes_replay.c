static void add_ie(struct lx_target *t,bool wpa1,unsigned pair,unsigned group,unsigned akms,unsigned caps)
{
    uint8_t *ie=t->elements+t->elements_length;unsigned n=2;
    const uint8_t oui[3]={0,wpa1?0x50:0x0f,wpa1?0xf2:0xac};
    ie[0]=wpa1?221:48;
    if(wpa1){memcpy(ie+n,oui,3);ie[n+3]=1;n+=4;}
    ie[n++]=1;ie[n++]=0;memcpy(ie+n,oui,3);ie[n+3]=group;n+=4;
    ie[n++]=1;ie[n++]=0;memcpy(ie+n,oui,3);ie[n+3]=pair;n+=4;
    ie[n++]=(akms&4?1:0)+(akms&256?1:0);ie[n++]=0;
    if(akms&4){memcpy(ie+n,oui,3);ie[n+3]=2;n+=4;}
    if(akms&256){memcpy(ie+n,oui,3);ie[n+3]=8;n+=4;}
    if(!wpa1){ie[n++]=caps;ie[n++]=0;}
    ie[1]=n-2;t->elements_length+=n;t->capability=0x10;
}
static void trial(struct lx_target t,struct hakios_sta_join wanted,bool success,bool wpa1,unsigned pair,unsigned group,bool pmf)
{
    struct lx_radio radio={.target=t};
    const char *error=protection(&radio.target,&wanted,&radio.security);
    if((error==NULL)!=success)fprintf(stderr,"backend mode=%d unexpected=%s\n",wanted.security,error?error:"accepted");
    assert((error==NULL)==success);checks++;
    if(!success)return;
    assert(radio.security.wpa1==wpa1&&radio.security.pairwise==pair&&radio.security.group==group&&radio.security.pmf==pmf);
    radio.sae=radio.security.sae;radio.h2e=radio.security.h2e;
    struct linuxkpi_ieee80211_channel channel={.band=0,.center_freq=2412,.max_power=20};
    struct ieee80211_supported_band band={.n_bitrates=1};band.bitrates[0].bitrate=10;
    typeof(*radio.channel) cc={.def.chan=&channel};typeof(*radio.wiphy) phy={.bands={&band,NULL}};
    typeof(*radio.vif) vif={.bss_conf.basic_rates=1};radio.channel=&cc;radio.wiphy=&phy;radio.vif=&vif;
    radio.width=20;radio.want_length=1;radio.want[0]=0xa1;memset(radio.pmkid,0xb2,16);
    uint8_t frame[512]={0};unsigned length=request_elements(&radio,frame,group);assert(length<sizeof(frame));
    const uint8_t oui[4]={0,80,242,1};const uint8_t *rsn=element(frame,length,48),*wpa=vendor_element(frame,length,oui);
    if(wanted.security==HAKIOS_STA_OPEN){assert(!rsn&&!wpa&&!radio.rsn_length);return;}
    assert(wpa1?(wpa&&!rsn):(rsn&&!wpa));
    struct hakios_security out;const uint8_t *ie=wpa1?wpa:rsn;
    assert(!hakios_security_read(ie,ie[1]+2,&out));
    assert(out.wpa1==wpa1&&out.pairwise==(1u<<pair)&&out.group==group);
    assert(out.akms==(1u<<(radio.sae?8:2))&&radio.wpa.rsn_length==radio.rsn_length);
    if(pmf)assert((out.capabilities&0x80)&&out.management_cipher==6);
    if(radio.sae)assert(out.pmkid_count==1&&(out.capabilities&0x40));
    checks++;
}
int main(void)
{
    struct lx_target t={.found=true};struct hakios_sta_join w={.security=HAKIOS_STA_OPEN};
    trial(t,w,true,false,0,0,false);t.capability=0x10;trial(t,w,false,false,0,0,false);
    for(unsigned legacy=0;legacy<2;legacy++)for(unsigned pair=2;pair<=4;pair+=2)for(unsigned group=2;group<=4;group+=2){
        t=(struct lx_target){.found=true};add_ie(&t,legacy,pair,group,4,0);
        w=(struct hakios_sta_join){.security=legacy?HAKIOS_STA_WPA_PSK:HAKIOS_STA_WPA2_PSK};
        trial(t,w,true,legacy,pair,group,false);
        w.pairwise_cipher=pair;w.group_cipher=group;trial(t,w,true,legacy,pair,group,false);
        w.security=HAKIOS_STA_OPEN;trial(t,w,false,false,0,0,false);
    }
    t=(struct lx_target){.found=true};add_ie(&t,true,2,2,4,0);add_ie(&t,false,4,2,4,0);
    w=(struct hakios_sta_join){.security=HAKIOS_STA_WPA_AUTO};trial(t,w,true,false,4,2,false);
    w.security=HAKIOS_STA_WPA_PSK;trial(t,w,true,true,2,2,false);
    w.security=HAKIOS_STA_WPA2_PSK;trial(t,w,true,false,4,2,false);
    for(unsigned caps=0;caps<256;caps++){
        t=(struct lx_target){.found=true};add_ie(&t,false,4,4,4|256,caps);
        w=(struct hakios_sta_join){.security=HAKIOS_STA_WPA3_SAE};trial(t,w,(caps&128)!=0,false,4,4,true);
        w.security=HAKIOS_STA_WPA2_PSK;trial(t,w,!(caps&64),false,4,4,false);
        w.management_protection=128;trial(t,w,(caps&128)!=0,false,4,4,true);
    }
    t=(struct lx_target){.found=true};add_ie(&t,false,4,4,256,192);w=(struct hakios_sta_join){.security=HAKIOS_STA_WPA2_PSK};
    trial(t,w,false,false,0,0,false);
    t=(struct lx_target){.found=true};add_ie(&t,false,4,4,4,0);w.security=HAKIOS_STA_WPA_PSK;trial(t,w,false,false,0,0,false);
    puts("PASS actual backend six modes, explicit AKM, CCMP/TKIP, PMF and association elements");printf("checks=%u\n",checks);
    return 0;
}
