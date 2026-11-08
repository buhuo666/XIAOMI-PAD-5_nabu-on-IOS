extern "C" int nabu_ath10k_driver_transmit(const unsigned char *bytes,unsigned long n){
    last_sent.assign(bytes,bytes+n);entered_tx=true;
    wait_for([]{return !hold_tx.load();});return send_errno;
}
extern "C" void nabu_wlan_runtime_lost(){live=false;nabu_wlan_service_invalidate(ENXIO);}
static int raw_power(bool on){assert(!tx_active);++power_calls;raw_phase=on?HAKIOS_STA_IDLE:HAKIOS_STA_OFF;return 0;}
static int raw_scan(const hakios_sta_scan *){return scan_errno;}
static int raw_leave(){assert(!tx_active);++leave_calls;raw_phase=HAKIOS_STA_IDLE;nabu_ath10k_os_net_link(0);return 0;}
static void raw_state(struct hakios_sta_state *s){s->phase=raw_phase;}
static int raw_join(const hakios_sta_join *){
    assert(!tx_active&&!bsd_up);
    nabu_ath10k_os_net_link(0); // raw join's old-station cleanup must not cancel this new attempt.
    if(join_errno)return join_errno;
    raw_phase=HAKIOS_STA_JOINED;nabu_ath10k_os_net_link(1);assert(!bsd_up);
    if(lose_in_join)nabu_ath10k_os_station_lost(ECONNRESET);
    if(fatal_in_join)nabu_wlan_runtime_lost();
    return 0;
}
static uint64_t counter(uint64_t *p){IOLockLock(gate);auto n=*p;IOLockUnlock(gate);return n;}
static void join_ok(const hakios_sta_join &what){allow_commit=true;assert(station_join(&what)==0);assert(bsd_up);}
int main(){
    nabu_wlan_service_publish();assert(!attaches);selected=true;nabu_wlan_service_publish();
    nabu_wlan_service_publish();assert(attaches==1);
    hakios_sta_ops raw={};raw.power=raw_power;raw.scan=raw_scan;raw.join=raw_join;raw.leave=raw_leave;raw.state=raw_state;
    uint8_t wrong[6]={0};nabu_ath10k_os_net_attach(wrong);nabu_ath10k_os_station(&raw);assert(!attached_ops);
    nabu_ath10k_os_net_attach(address);live=false;nabu_ath10k_os_station(&raw);assert(!attached_ops);
    live=true;nabu_ath10k_os_station(&raw);assert(attached_ops&&attached_ops->join);
    Packet packet;packet.bytes.assign(64,0x5a);
    assert(!transmit(&packet,64));nabu_ath10k_os_net_input(packet.bytes.data(),64);assert(!rx_calls);
    hakios_sta_scan scan={};scan_errno=ETIMEDOUT;assert(station_scan(&scan)==ETIMEDOUT);
    hakios_sta_join what={};what.security=HAKIOS_STA_WPA2_PSK;
    join_errno=EACCES;assert(station_join(&what)==EACCES&&!bsd_up);join_errno=0;
    join_ok(what);nabu_ath10k_os_net_input(packet.bytes.data(),64);assert(rx_calls==1);
    packet.bad=true;assert(!transmit(&packet,64));packet.bad=false;
    assert(!transmit(&packet,13)&&!transmit(&packet,1515));
    hold_tx=true;entered_tx=false;assert(transmit(&packet,64));wait_for([]{return entered_tx.load();});
    packet.bytes.assign(64,0xa5);assert(last_sent[0]==0x5a); // caller can reuse/free its mbuf.
    for(unsigned i=0;i<queue_capacity;i++)assert(transmit(&packet,64));
    assert(!transmit(&packet,64));
    std::atomic<bool> off_done{false};std::thread off([&]{assert(station_power(false)==0);off_done=true;});
    wait_for([]{return !bsd_up.load();});assert(!off_done&&!power_calls);
    assert(!transmit(&packet,64));hold_tx=false;off.join();assert(power_calls==1&&counter(&tx_returned)==1);
    assert(queue_count==0&&counter(&tx_dropped)>=queue_capacity);
    assert(station_power(true)==0);join_ok(what);
    auto before=counter(&tx_returned);send_errno=ENOBUFS;assert(transmit(&packet,64));
    wait_for([&]{return counter(&tx_returned)>before;});assert(counter(&tx_errors)==1);send_errno=0;
    assert(station_leave()==0&&!bsd_up);join_ok(what);
    nabu_ath10k_os_station_lost(EIO);assert(!bsd_up&&attached_ops&&hakios_sta_powered());
    nabu_ath10k_os_net_input(packet.bytes.data(),64);assert(rx_calls==1);join_ok(what);
    allow_commit=false;auto leaves=leave_calls.load();assert(station_join(&what)==ECANCELED&&!bsd_up);assert(leave_calls==leaves+1);
    lose_in_join=true;allow_commit=true;assert(station_join(&what)==ECANCELED&&!bsd_up);lose_in_join=false;
    join_ok(what);
    // New join drops queued old-network frames and waits for the active transmitter.
    hold_tx=true;entered_tx=false;assert(transmit(&packet,64));wait_for([]{return entered_tx.load();});
    assert(transmit(&packet,64));std::atomic<bool> rejoined{false};allow_commit=true;
    std::thread rejoin([&]{assert(station_join(&what)==0);rejoined=true;});wait_for([]{return !bsd_up.load();});
    assert(!rejoined);hold_tx=false;rejoin.join();assert(bsd_up&&queue_count==0);
    hold_tx=true;entered_tx=false;assert(transmit(&packet,64));wait_for([]{return entered_tx.load();});
    nabu_wlan_runtime_lost();assert(!bsd_up&&!attached_ops);assert(tx_active==1); // fatal did not drain/block.
    assert(!transmit(&packet,64));nabu_ath10k_os_net_input(packet.bytes.data(),64);assert(rx_calls==1);
    hold_tx=false;nabu_ath10k_os_station(nullptr);assert(!backend&&!tx_active&&attaches==1);
    // Fatal during late raw join success must not issue a second raw leave.
    live=true;nabu_ath10k_os_station(&raw);allow_commit=true;fatal_in_join=true;leaves=leave_calls.load();
    assert(station_join(&what)==ECANCELED&&!bsd_up);assert(leave_calls==leaves);
    nabu_ath10k_os_station(nullptr);nabu_wlan_service_summary();
    IOLockLock(gate);stopping=true;IOLockWakeup(gate,&queue_count,false);IOLockUnlock(gate);tx_thread.join();
    free(queue);for(auto *p:all_locks)delete p;
    puts("adapter actual-source queue, copy, error, drain, rejoin, AP-loss and fatal cases passed");
}
