#!/usr/bin/env python3
"""Run production frame construction/sending through ath10k's actual sequence helper."""
import argparse,json,re,subprocess,sys
from pathlib import Path
from check_darwinboot_8796 import host_command,host_path
from check_nabu_ath10k_station import C_TOKEN

def function(source,name):
    at=re.search(r'\b'+name+r'\([^;]*?\)\s*\{',source)
    start=source.rfind('\nstatic ',0,at.start())+1
    depth=1
    for token in C_TOKEN.finditer(source,at.end()):
        if token.group()=='{':depth+=1
        elif token.group()=='}':
            depth-=1
            if not depth:return source[start:token.end()]
    raise ValueError(name)

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--mac',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--expect-zero',action='store_true');p.add_argument('--expect-no-iv',action='store_true');a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    host=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define ETH_ALEN 6
#define NL80211_BAND_2GHZ 0
#define IEEE80211_TX_CTL_ASSIGN_SEQ (1u<<1)
#define IEEE80211_TX_CTL_FIRST_FRAGMENT (1u<<12)
#define IEEE80211_TX_CTL_HW_80211_ENCAP (1u<<27)
#define IEEE80211_KEY_FLAG_GENERATE_IV_MGMT (1u<<5)
#define IEEE80211_SCTL_FRAG 15
#define cpu_to_le16(x) (x)
struct ath10k_vif {uint16_t tx_seq_no;};
struct ieee80211_vif {uint8_t addr[6];void *drv_priv;};
struct ieee80211_key_conf {unsigned flags,keyidx;uint64_t tx_pn;};
static uint64_t atomic64_inc_return(uint64_t *p) __attribute__((unused));
static uint64_t atomic64_inc_return(uint64_t *p){return ++*p;}
struct ieee80211_tx_info {unsigned flags;struct {struct ieee80211_vif *vif;struct ieee80211_key_conf *hw_key;} control;unsigned band;};
struct ieee80211_hdr {uint8_t bytes[22];uint16_t seq_ctrl;};
struct sk_buff {uint8_t *data,*storage;unsigned len;struct ieee80211_tx_info info;};
#define IEEE80211_SKB_CB(s) (&(s)->info)
struct ieee80211_tx_control {void *sta;};
struct hw {int unused;};
struct ops {void (*tx)(struct hw *,struct ieee80211_tx_control *,struct sk_buff *);};
struct channel {struct {struct {unsigned band;} *chan;} def;};
struct lx_radio {struct ieee80211_vif *vif;void *sta;struct channel *channel;bool sae;struct ieee80211_key_conf *pairwise_key;struct ops *ops;struct hw hw;struct {uint8_t address[6];} target;unsigned sent,sent_lost;};
static struct sk_buff *dev_alloc_skb(unsigned n){struct sk_buff *s=calloc(1,sizeof *s);s->storage=s->data=calloc(1,n);return s;}
static void skb_reserve(struct sk_buff *s,unsigned n){s->data+=n;}
static uint8_t *skb_put(struct sk_buff *s,unsigned n){s->len=n;return s->data;}
static uint8_t *skb_push(struct sk_buff *s,unsigned n) __attribute__((unused));
static uint8_t *skb_push(struct sk_buff *s,unsigned n){s->len+=n;s->data-=n;return s->data;}
static bool ieee80211_is_robust_mgmt_frame(struct sk_buff *s){return !(s->info.flags&IEEE80211_TX_CTL_HW_80211_ENCAP)&&(s->data[0]==0xc0||s->data[0]==0xd0);}
static uint16_t seqs[16];static unsigned count;static uint8_t observed[64];static unsigned flags,length;static void *key;
'''
    chunks=[host,function(a.mac.read_text(),'ath10k_tx_h_seq_no'),r'''
static void tx(struct hw *hw,struct ieee80211_tx_control *ctl,struct sk_buff *skb){
 (void)hw;assert(ctl->sta);flags=skb->info.flags;key=skb->info.control.hw_key;length=skb->len;
 if(!(flags&IEEE80211_TX_CTL_HW_80211_ENCAP))ath10k_tx_h_seq_no(skb->info.control.vif,skb);
 seqs[count++]=((struct ieee80211_hdr *)skb->data)->seq_ctrl;memcpy(observed,skb->data,skb->len);
 free(skb->storage);free(skb);
}
''']
    source=a.source.read_text()
    names=['frame_new']
    if 'management_ccmp_header(' in source:names.append('management_ccmp_header')
    names+=['frame_send','management','ethernet_send']
    for name in names:chunks.append(function(source,name))
    chunks.append(r'''
int main(void){
 struct ath10k_vif ar={0};struct ieee80211_vif vif={{1,2,3,4,5,6},&ar};struct ops ops={tx};
 struct lx_radio r={.vif=&vif,.sta=&ar,.ops=&ops};uint8_t *body;
 /* SAE commit/confirm/retransmitted confirm and association are distinct MPDUs. */
 for(unsigned i=0;i<4;i++){struct sk_buff *s=frame_new(&r,30,&body);body=management(&r,body,i==3?0:0xb0);body[0]=3;body[2]=i?2:1;frame_send(&r,s);}
#if EXPECT_ZERO
 for(unsigned i=0;i<4;i++)assert(seqs[i]==0);
#else
 for(unsigned i=0;i<4;i++)assert(seqs[i]==0x1010+i*0x10);
#endif
 /* Ethernet payload must remain byte-identical, regardless of its first byte. */
 uint8_t ethernet[30];memset(ethernet,0xb0,sizeof ethernet);assert(ethernet_send(&r,ethernet,sizeof ethernet));
 assert(!memcmp(ethernet,observed,sizeof ethernet));assert(flags==IEEE80211_TX_CTL_HW_80211_ENCAP);
 /* Protected management retains key selection and increments its sequence. */
 struct ieee80211_key_conf ccmp={.flags=IEEE80211_KEY_FLAG_GENERATE_IV_MGMT,.keyidx=0,.tx_pn=0};
 r.sae=true;r.pairwise_key=&ccmp;struct sk_buff *s=frame_new(&r,26,&body);body=management(&r,body,0xc0);body[0]=3;body[1]=0;frame_send(&r,s);
 assert(key==&ccmp&&(observed[1]&0x40));
#if EXPECT_NO_IV
 assert(length==26&&ccmp.tx_pn==0);
#else
 const uint8_t iv1[8]={1,0,0,0x20,0,0,0,0};
 assert(length==34&&!memcmp(observed+24,iv1,8)&&observed[32]==3&&observed[33]==0);
 /* Driver appends 8 MIC bytes: complete deauthentication is 24+8+2+8. */
 assert(length+8==42&&ccmp.tx_pn==1);
 assert(!memcmp(observed+10,vif.addr,6));
#endif
#if !EXPECT_ZERO
 assert(seqs[5]==0x1050);
 /* The native helper wraps at 4096 sequence numbers and preserves fragment bits. */
 ar.tx_seq_no=0xffe0;s=frame_new(&r,26,&body);management(&r,body,0xd0);frame_send(&r,s);assert(seqs[6]==0xfff0);
 s=frame_new(&r,26,&body);management(&r,body,0xd0);frame_send(&r,s);assert(seqs[7]==0);
#endif
#if !EXPECT_NO_IV
 ccmp.tx_pn=0x01020304ffffULL;ccmp.keyidx=2;
 s=frame_new(&r,28,&body);body=management(&r,body,0xd0);memcpy(body,"SAQR",4);frame_send(&r,s);
 const uint8_t carry[8]={0,0,0,0xa0,5,3,2,1};
 assert(length==36&&!memcmp(observed+24,carry,8)&&!memcmp(observed+32,"SAQR",4));
 uint64_t saved_pn=ccmp.tx_pn;assert(ethernet_send(&r,ethernet,sizeof ethernet));assert(ccmp.tx_pn==saved_pn);
 /* Hardware IV generation without this flag must not insert a second header. */
 ccmp.flags=0;s=frame_new(&r,26,&body);management(&r,body,0xc0);frame_send(&r,s);assert(length==26&&ccmp.tx_pn==saved_pn);
#endif
 puts("PASS actual management/ethernet paths, SAE sequence progression, PMF key and wrap");return 0;
}
''')
    unit=out/'actual.c';unit.write_text('\n'.join(chunks));results=[]
    for mode,extra in [('release',['-O2']),('sanitizers',['-fsanitize=address,undefined','-fno-sanitize-recover=all','-g'])]:
        binary=out/mode
        command=['clang' if sys.platform=='darwin' else 'clang-18','-std=gnu11','-Wall','-Wextra','-Werror',f'-DEXPECT_ZERO={int(a.expect_zero)}',f'-DEXPECT_NO_IV={int(a.expect_zero or a.expect_no_iv)}',*extra,host_path(unit),'-o',host_path(binary)]
        build=subprocess.run(host_command(command),capture_output=True);(out/(mode+'-build.log')).write_bytes(build.stdout+build.stderr)
        if build.returncode:raise RuntimeError((build.stdout+build.stderr).decode(errors='replace'))
        run=subprocess.run(host_command([host_path(binary)]),capture_output=True);(out/(mode+'.log')).write_bytes(run.stdout+run.stderr)
        if run.returncode:raise RuntimeError((run.stdout+run.stderr).decode(errors='replace'))
        results.append(dict(mode=mode,result=0))
    (out/'report.json').write_text(json.dumps(dict(passed=True,source=str(a.source),mac=str(a.mac),baseline_zero=a.expect_zero,results=results,device_tested=False),indent=2)+'\n')
    print('Management sequence production-path tests passed',results)
if __name__=='__main__':main()
