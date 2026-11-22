2026-11-20 WSL 迁移规则（最新用户要求）：项目只使用 Ubuntu-24.04，Windows 构建命令显式使用 `wsl -d Ubuntu-24.04 -- ...`，不要再启动 Ubuntu-22.04。22.04 的 /home/buhuo 已迁入 24.04 相同路径并通过归档逐文件比较；24.04 默认用户 buhuo，已有 /root/m2v* 工作区保留，访问这些原有 root 工作区使用 `-u root`。D 盘共享工程仍使用 /mnt/d，当前工作树 /mnt/d/CodexData/home/worktrees/nabu-app-store/XIAOMI_PAD5-NABU。迁移记录 D:/github-IOS/wsl-migration-20261120/迁移报告.md；22.04 完整导出保存在同目录，用户自行决定删除原分发版。

2026-11-20 内核编译接续更正：此前将一次未披露具体操作的历史 agent-turn 报错解释为持续编译禁令，属于过度推断。用户已明确选择继续执行；不要再要求用户查找不存在的解除状态工具或记录。正常项目构建按当前授权和工具检查继续；若发生新的具体拒绝，按该拒绝处理，不绕过。旧报错证据保留为历史。当前实际编译缺口是从匹配 XNU/HakiOS 配置生成真实 mach_assert.h，随后编译 receive 对象并组装独立 REN325 包；本次仅迁移 WSL，未编译最终内核、未操作设备。

2026-11-18 WTH320 r3 compactconfig Enable/readback PASS, root285, Weather286 native-hooks-ready BUT NOdata. Exactlegacy witness0x1a4b284c4 bypasses hookedexport0x1a4b28028; actualweatherd269 ignored2SIGTERM. Provider r2 117632B signed/atomicuploaded, NSURLProtocol nowaccepts originalAppleweatherHTTP(S) aswellas nabu-weather; publicfreshrequestdoesnotforwardauth. Bridge r4 INSTALLED USERREOPEN PENDING, SIGKILLonlyweatherd + SIGTERMWeather; SBSlaunchWeather automatic/named LaunchWeather/RefreshWeather available. r3root285 Stop verified; noactivehelperuntiluseropen. Fresh900s capture73313 log/host/WTH320/provider-live-r2.log running. KeepSET318/locationaccepted/nokernelorlogslotwrite; protectslot1/span8 UUID91fa1f796b42437cafd6038ff4fff06c. State analysis/weather-WTH320/continuation.json. Historical entries follow.

2026-11-18 WTH320 actual deviceObjCmapper PASS(current+263h+11d); r2c Enable FAILED because retainedSET318 kernel exec_inject capacity512, baseline509B, proposed660B. r2c root283 replayed oldStop/exited. r3 fixes compact aliases /tmp/ns->acceptedsetup,/tmp/nw->provider, one Weather/weatherd rule totals510B inclNUL; actualoriginalkernelparser23cases preserve allbaseline library/filter semantics PASS. Captures prelaunchID; errno logged. r3signed/INSTALLED USERREOPEN PENDING. Provider r1b unchanged uploaded117440B; originalSwiftdecoder/weatherUI stillUNTESTED. KeepSET318/locationaccepted/no reboot/no logslotwrite; protectslot1/span8 UUID91fa1f796b42437cafd6038ff4fff06c. State analysis/weather-WTH320/continuation.json. Historical entries follow.

2026-11-18 WTH320 public-weather-provider r1b signed/uploaded117440B; WeatherBridge r2c installed, USER REOPEN PENDING. Original Weather/weatherd transport adapter uses retainedElleKit, publicOpenMeteo real3products; 14sourcecontract checks/compile PASS, actualnativeMapper+Swiftdecoder/UI NOTTESTED. OldrootPID273 Stop verified. Newhelper firstruns actualObjCmapper on uploadedrealfixture, then enables2Weather/weatherd rules preserving others and restarts onlythese2; logs mapper-validation/provider.log. Live900s syslog session94669 log/host/WTH320/provider-live-r1b.log active. KeepSET318/no reboot/no kernel/logslotwrite; location accepted retained. Protectslot1/span8 UUID91fa1f796b42437cafd6038ff4fff06c. State analysis/weather-WTH320/continuation.json. Historical entries follow.

2026-11-18 LOC319 user location menu/switch/app permissions ACCEPTED in currentSET318 boot. Actual4services absent before; restored originalCommCenter-noncellular+2helpers+locationd via rootApp/nativeUSB. NoMG/UIforcedvalues/noauthorizationoverwrite. r1diagnostic POSIX13 falsefailure corrected; r2signed/installed/notrerun. LOC319bootstrap offlineAPFS/readback7PASS, other467filesexact; NOTDEPLOYED/crossrebootUNVALIDATED. KeepcurrentiPadOS; no reboot/no logslotwrite. ProtectSET318 slot1/span8 UUID91fa1f796b42437cafd6038ff4fff06c untilfull512MiBcollection. State analysis/location-LOC319/continuation.json. Historical entries follow.

2026-11-17 CHG311 Settings repro captured: Notifications Preferences1730/BulletinBoardController SIGABRT6 from missing NBLibrary externFunctionNames at21:56:20. ScreenTimeAgent121 missing remotemanagementd data directory -> errno2/CoreData512/XPC4097/repeated requests/SQLite14; actual hung-thread attribution pending. Additional NSURL nil Safari page crashes kept separate. Notifications selector candidate compiled/signed457exports preserved NOTdeployed; SettingsRepair App org.nabu.SettingsRepair INSTALLED/notrun, creates onlymissing501:5010700directory and kickstarts onlyScreenTimeAgent after thread snapshot. KeepCHG311/nativeUSB; followup900s capture96354 active. OwnerSTOPPED; protectslot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9 untilfull512MiB+latency. State analysis/settings-CHG311/continuation.json. Historical entries follow.

2026-11-17 CHG311 Settings failing pages CONFIRMED: Notifications and Screen Time. Current exception/termination still unobserved; live900s syslog35390 settings-repro.log active. Preserve currentiPadOS/nativeUSB for reproduction; noAndroidtransition yet. Stockcrashfiles0; no cause inferred from oldSQLite6922 or omitted84jobs. ALS/keyboard/charging accepted retained; ownerSTOPPED; nativefinalsaved; slot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9 protected untilfull512MiB+latency. State analysis/settings-CHG311/continuation.json. Historical entries follow.

2026-11-17 CHG311 user reports some Settings entries immediate exit; exactpages PENDING. Keep currentiPadOS/nativeUSB for reproduction, noAndroidtransition yet. Initialstockcrashfiles0; syslog300s capture77957 log/host/CHG311/settings-live.log active. Prior generalSettingspass doesnotcover allpages; rootservice snapshot notfaultdiagnosis. ALS/keyboard/charging accepted retained; ownerSTOPPED; nativefinal saved; slot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9 protected untilfull512MiB+latency. State analysis/settings-CHG311/continuation.json. Historical entries follow.

2026-11-17 CHG311 rootservice snapshot complete: original485labels retained401/omitted84; retained412unique registered399/idle231/unregistered13 (4Disabled,5hardware-mode,3featureflags,1LaunchOnlyOnce). Full launchd458registered/201running/257idle, last nonzeroexit0; IORegistry222nodes/56classes/150clients/3busyancestors. Nativefinal108133344B/965465samples/4stop/drop0/nonmonotonic0/finishIOKit0; controls73fail/rejected10 retained; StopSessioncleanup10053 after allfiles copied, USBstillpresent. ownerSTOPPED. AwaitmanualAndroid forfull512MiB+latency; slot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9 PROTECTED. Report analysis/services-CHG311/service-audit.md. Historical entries follow.

2026-11-17 CHG311 read-only kernel/system audit: nonroot process count220/named171,49unresolved; USB stock services PASS, diagnostics returns emptyregistry. Wireless interface/controller published;3busy ancestors not failures. New standalone ServiceAudit App installed/signed24slots; user physical open/start PENDING for rootfullregistry/launchctl snapshots. Accepted drivers/kernel unchanged; ownerRUNNING; slot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9 protected, finalnative/full512MiB+latency PENDING. State analysis/services-CHG311/continuation.json. Historical entries follow.

2026-11-17 CHG311 user charging and returnPC normal PASS; final native USB configuration2/500mA, AFC/installproxy/SpringBoard requests PASS. Actual foreground wall sample13s/14samples includes4switching-negative+10positive, ICL1500; no3min stability claim. UI/keyboard accepted. Current-boot read-only kernel/system service audit active; ownerRUNNING. Protectslot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9; finalnative/full512MiB/clear/readback+same-run latency still PENDING. State log/host/CHG311/continuation.json. Historical entries follow.

2026-11-17 CHG311 user confirms desktop/settings/touch/physical keyboard normal; crash/jitter/black-wallpaper acceptance PASS. Real keyboard keys130 observed; later attached0 retained as detach state. Native ALS curve8coords +1.5/4 timing readback PASS. Same-boot PC->wall->PC USB charging roundtrip PENDING; ownerRUNNING. Protect slot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9 until final native/full512MiB collection, clear/readback. State D:/github-IOS/XIAOMI_PAD5-NABU/log/host/CHG311/continuation.json. Historical entries follow.

2026-11-17 CHG311 LIVE temporaryboot/nativeUSB PASS; actual policy plist replaced inthisboot, native curve8coords +1.5/4timing readback PASS;5176raw/drop0/owner0/iokit0 snapshot. Desktop/touch/keyboard physicalfeedback PENDING, latestkeyboardattached0; ownerRUNNING. Chargingroundtrip UNTESTED. Protectslot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9 untilfinalnative/full512MiB collection. Capture92612 240s. State log/host/CHG311/continuation.json. Historical entries follow.

2026-11-17 CHG311 reservedslot1/span8 UUIDd68fc0ff273f4d36bf26149d08526bb9 protectuntilfull512MiB recovery. OnlyALS indirect64pointer stub; vm_map preservesnearcachehint per8796source, signednormal+ASan/UBSan7cases PASS; bootstrap469files exceptALS+3trialplists/APFScheck/readbackPASS. ExactCHG310kernel andallotherbinaries/brightness/keyboard/rotation/display retained. Staging/notbooted. State log/host/CHG311/continuation.json. Historical entries follow.

2026-11-17 CHG310 collected full512MiB/9,438,484valid prefix unsealed; clear/readback and bootpartitions unchanged. Native19,988,224B/178455samples/drop0/4stop/finishACK15. PROVEN ALS directADRP rangefailure3 at32.317s precedeskeyboardattach91.778s; bri requested_curve nil dictionary objects3 -> backboardd SIGABRT107.210s. CHG311 indirect full64 pointer stub built/tests pass; bootstrap preparing, not reserved/deployed. Exact chargingkernel/keyboard/brightnesscurve/rotation/display retained. AndroidUSB/nooccupiedslot. State log/host/CHG310/continuation.json. Historical entries follow.

2026-11-17 CHG310 UI FAIL: backboardd16 uncaught NSInvalidArgumentException nil dictionary objects[3] at19:01:10, SIGABRT6; desktop restart/jitter/blackwallpaper userreported duringkeyboard. Keyboardattached1, retainedbinaries; actualtrigger unresolved. Nativefinal19,988,224B/178455samples/drop0/4stop/finishACK15 saved; manualAndroidreturn requested. Protectslot1/span8 UUID2787863a562845b0bde59986e96878f7 untilfull512MiB recovery/clear/readback. ChargingUSBroundtrip UNTESTED. State log/host/CHG310/continuation.json. Historical entries follow.

2026-11-17 CHG310 reserved slot1/span8 UUID 2787863a562845b0bde59986e96878f7; protect until full512MiB recovery. Actual source-gated USB data, OCP1500 charging retained; 87/89 objects exact CHG309, keyboard5 objects/frontend exact.24 ADT nodes same CHG307 except seed, 588 args except310, all469 bootstrap files except3trial values. ASan/UBSan/21 overlays/loader pass. Staging, device not yet tested. State log/host/CHG310/continuation.json. Historical entries follow.

2026-11-17 CHG309 full 512MiB / 6,687,607B valid prefix recovered, cleared/readback; boot partitions unchanged. Wall OCP 1500mA stable 482s / 483 samples all positive, mean +710.27mA, capacity84->85 PASS. USB worker stopped252.538s after unsupported CONNECTDONE on DCP; returnPC configuration0/100mA FAIL. Read-only Data recovery saved charge/native files; no normal stop ACK, unsealed log and raw-tail retained. Keyboard5objects/2libs/config exactCHG307; user corrected physicallyCONNECTED, onlyasksretention; reportedattached0/keys0 retained. CHG310 data-source gate tests ASan/UBSan passed, kernel-r4 linking; no new reservation/deployment. State log/host/CHG309/continuation.json. Historical entries follow.

2026-11-17 CHG309 LIVE：用户确认桌面、设置、触摸正常，原生 USB 与四路 SensorHub 输入已取得；电脑配置 2、输入限流 500mA，亮屏净电流约 -374..-290mA。已请求同一正常充电器亮屏 3 分钟后接回电脑，当前 USB 数据断开，充电器实际结果待回传。owner 未停止。slot1/span8 UUID d9eadaa4fa3c45af93d8101d2338ea5c 占用，完整 512MiB 未回收前禁止覆盖。恢复完整 CHG307 ADT/身份/固件与两处返回追踪，588 字节参数，仅编号 309；accepted SEN305 二进制保留。实时状态 log/host/CHG309/continuation.json。以下为历史。

2026-11-17 CHG309 freshslot1/span8 UUIDd9eadaa4fa3c45af93d8101d2338ea5c protecteduntilfull512MiB. CorrectedOCPcharge-r3-return-trace plusCHG307 fullADT/acceptedSEN305binaries.24ADTnodes/14,314,628B exactCHG307exceptseed;588args except309;469files except3trialplists.21overlays/loaderPASS. Deploymentpreparing; chargingUNVALIDATED. State log/host/CHG309/continuation.json. Historical entries follow.

2026-11-17 CHG308 FAILED Logo. Compared actual ESP with CHG307: checkpoint0->12; missingGPU/BT/modem/WLAN ADT nodes andacceptedidentities/RTC/keys; two returntrace jumps omitted. All469APFSfiles retainedexcept3trialplistvalues, binariesexact. Full512MiB/0committedbytes recovered-clear/readback. Correctedofflinecandidate nabu-chain-CHG308-corrected-r1 preservesCHG307ADTexceptseed,checkpoint0+trace;21overlays/actualloaderPASS; UNRESERVED/NOTDEPLOYED. USBcharge stillUNVALIDATED. State log/host/CHG308/continuation.json. Historical entries follow.

2026-11-17 SEN302 temporaryboot commandPASS; actual588byteargs/kernel/UUID bound. NativeUSBcapture79789 and physicalrotation/brightness feedback PENDING. Core-r17 ALSPrimaryUsage properties +sen.dylib originalorientation init selection; exactowner/ALS preserved. Protectslot1/span8 UUID8582b4be4c5f40d6905bd6244e74a62a untilfull512MiB recovery. State log/host/SEN302/continuation.json. Historical entries follow.

2026-11-17 SEN302 reservedslot1/span8 UUID8582b4be4c5f40d6905bd6244e74a62a protected untilfull512MiB recovery. OnlyRawSourcePrimaryUsage pair plusoriginalbackboardorientation, exactSEN301 nativeowner/ALS reused. Stagingpending. State log/host/SEN302/continuation.json. Historical entries follow.

2026-11-17 SEN301 full512MiB/10763894valid unsealed collected-clear/readback,bootunchanged; AndroidUSB/nooccupiedslot.664073raw+4stop/drop0/nonmonotonic0,finishACK63;600s originalCMfusion31595PASS,gyro unitsPASS; independentorientation38callbacks sixfacescorrect. AutoBrightness switchABSENT; systemrotation notyetintegrated. SSCcontrols25rejected,cleanupretained0. SEN300attach-1 NOTreproduced/fixunproven. State log/host/SEN301/continuation.json. Historical entries follow.

2026-11-17 SEN301 LIVE desktop/Settings/touchPASS. Raw resumed;600s originalsoftwarefusion 31595CMmotion, errors0/nonmonotonic0;CMgyro31595 exactrawtick matches,max4.77e-7rad/s. Sixfaces andmotion/light marked;XYZ directions supported. Independent directionApp org.nabu.SensorHubOrientationProbe installed, notlaunchverified; autoBrightness anddirection userfeedback PENDING. Owner STILLRUNNING, no stoprequest;52.3MB raw live snapshot saved, notfinal. Protectslot1/span8 UUID5f5e96ac0fc64d6daa313c887f3525b7 untilfinalnative+full512MiB recovery. SEN300 attach-1 cause NOTfixed. State log/host/SEN301/continuation.json. Historical entries follow.

2026-11-17 SEN301 temporaryboot commandPASS; actual588byteargs/kernel/UUID verified. NativeUSBcapture17224 and physicalfeedback pending. Onlyattachwire diagnostics; nativeSEN300 binaries preserved. Protectslot1/span8 UUID5f5e96ac0fc64d6daa313c887f3525b7 untilfull512MiB recovery. State log/host/SEN301/continuation.json. Historical entries follow.

2026-11-17 SEN301 fresh log reservation slot1/span8 UUID5f5e96ac0fc64d6daa313c887f3525b7 protected untilfull512MiB recovery. Onlyfirst-attach diagnostics;88/89objects unchanged, exactSEN300 native binaries. Preparingdeployment, no hardwarepass yet. State log/host/SEN301/continuation.json. Historical entries follow.

2026-11-17 SEN300 full512MiB/3833250valid unsealed collected, cleared/readback and bootunchanged. Userdesktop/Settings/touchPASS; firstFastRPC attach=-1, SSC neverstarted, raw0; softwareselectionPASS butgyro/fusionuntested. Kernelshutdownretained0. AndroidUSB/nooccupiedslot. Investigateattach failure againstSEN299; no blindretry/no acceptedcomponent changes. State log/host/SEN300/continuation.json. Historical entries follow.

2026-11-17 SEN300 userdesktop/Settings/touchPASS but nativeinputs0: ownerbin/trace0,nosummary; observercapability413338874->413338850 readback/restorePASS,allchannels emptyat257s. Stopmarkerwritten,nofinishACK. Androidrecoveryrequested PENDING. Protectslot1/span8 UUID65194aae003b49869975c0b0a5da42ac untilfull512MiB collection. Do not inferfusionfailurewithoutinput. State log/host/SEN300/continuation.json. Historical entries follow.

2026-11-17 SEN300 temporaryboot fastbootPASS; actual588byteargs/kernel/UUID verified. Newgyro units +independentfusionobserver; nativeUSBcapture18406 pending,physicalfeedback requested. Protectslot1/span8 UUID65194aae003b49869975c0b0a5da42ac untilfull512MiB collection. State log/host/SEN300/continuation.json. Historical entries follow.

2026-11-17 SEN300 reserved/staging. Gyrounitsfix+independentoriginalsoftwarefusionobserver; exactSEN299kernel/injectedlibs preserved. Protectslot1/span8 UUID65194aae003b49869975c0b0a5da42ac untilfull512MiB recovery. State log/host/SEN300/continuation.json. Historical entries follow.

2026-11-17 USER resumed sensorimplementation. SEN299 desktop/Settings/touchPASS and fullslot alreadycollected/cleared; originalALS AABC association proved. SEN300-r2 exactkernel/libs plusgyro unitsfix andindependentfusionobserver preparingfreshreservation; inspectreceipt beforeanyrepeatwrite. State log/host/SEN300/continuation.json. Historical entries follow.

2026-11-17 USER CLEARED GOAL duringSEN299 collection; completedinflightrecovery only. SEN299 desktop/Settings/touchPASS; full512MiB/23394427validunsealed collected-clear/readback bootunchanged. RealALS matches1 AABC0x1010e8000 created;235723samples shutdownretained0. AndroidUSB/nooccupiedslot. STOP; SEN300-r2 offlineonly,notreserved/deployed. State log/host/SEN299/continuation.json. Historical entries follow.

2026-11-17 SEN299 STOPPED normally finishACK14; finalbin26402240B/235723samples+4stop/drop0 saved.10min originalCM3channels verified,gyro unitsfault hostfixed,fusion0. Userdesktop+Androidrecoveryfeedback PENDING; do not presumeAndroid. Protectslot1/span8 UUIDcf8a44493c2d4951964202a0b076e10c untilfull512MiB collection. SEN300-r2 offlineonly/unreserved. State log/host/SEN299/continuation.json. Historical entries follow.

2026-11-17 SEN299 nativeUSB/live; independentobserver600s COMPLETE realCM31592/31592/12491, HID4channels,errors0/nonmonotonic0,DeviceMotion0. Userdesktop/settings/touchfeedback PENDING. GyroHIDunits proven degrees/s,hostnative-r5 fixpassed/notdeployed. SeparatefusionprobeApp installed/notlaunched. Ownerstillrunning; NOstoprequested. Protectslot1/span8 UUIDcf8a44493c2d4951964202a0b076e10c; finalbin+full512MiB stillrequired. State log/host/SEN299/continuation.json. Historical entries follow.

2026-11-17 SEN299 temporaryboot fastbootPASS, actual588byteargs/kernel/UUID bound. LFconfig fix, nativeUSBcapture18925 waits. Protectslot1/span8 UUIDcf8a44493c2d4951964202a0b076e10c untilfull512MiB recovery; actualALS/nativecallbacks/physicalpending. State log/host/SEN299/continuation.json. Historical entries follow.

2026-11-17 SEN299 reserved/staging. LF510B injection fix, actual19process parser PASS; kernel/native binaries sameSEN298, acceptedcomponents preserved. Protectslot1/span8 UUIDcf8a44493c2d4951964202a0b076e10c untilfull512MiB recovery. State log/host/SEN299/continuation.json. Historical entries follow.

2026-11-17 SEN298 FAILED: packagedCRLF516B rejected kern.exec_inject error22; input/stylus/ALS injection absent, same nullAABC PC1af00e030.7335rawsamples/4stop/0drop; full512MiB/11242247valid collected-clear/readback,unsealedtail,bootunchanged. AndroidUSB/nooccupiedslot. SEN299 LF510B correction only; samekernel/native,19process actualparser checkPASS. SEN296 acceptedbaseline. State log/host/SEN298/continuation.json. Historical entries follow.

2026-11-17 SEN298 temporaryboot fastbootPASS, actual588byteargs/kernel/UUID bound; nativeUSBcapture37639 running. RealALS association runtimepending; userasked desktop/no-jitter and keepSEN298. Protectslot1/span8 UUID5a1871b12dcc4f83b25b08f2c4ccd504 untilfull512MiB collection. State log/host/SEN298/continuation.json. Historical entries follow.

2026-11-17 SEN298 realALS association candidate prepared: RawSourceaddsactualALS IOService; originalCoreBrightness scopedIDMatching to realnode beforeAABC.88of89kernelobjects sameSEN297,acceptedcomponents preserved. Native-r4/bootstrapSEN298 offline passed; hardwarepending. Protectslot1/span8 UUID5a1871b12dcc4f83b25b08f2c4ccd504 untilfull512MiB collection. State log/host/SEN298/continuation.json. Historical entries follow.

2026-11-17 SEN297 FAILED desktopjitter afterbackboardd SIGSEGV. ProvenCoreBrightness AABC null: PC1af00e030 ldr[x8+1c8],x8=0,LR1aefa6060 shouldMitigateHarmony; virtualALS lacksrealregistryassociation. Continuous19436samples4980/4980/9457/19,dropped0,finishACK1/fullshutdownretained0; observer0callbacks. Full512MiB/9492424valid collected-clear/readback bootunchanged;AndroidUSB/nooccupiedslot. SEN296 remainsaccepted; donotchangeacceptedGPU/display/input. State log/host/SEN297/continuation.json. Historical entries follow.

2026-11-16 SEN297 temporaryboot fastbootPASS, exact588byteargs/newkernel/UUID bound; nativeUSBcapture37618 running. Protectslot1/span8 UUIDa513b46db77a4843805e2c1b0e9f6b42 untilfull512MiB recovery. Nativeowner/observer/continuousraw actualruntime pending; userasked desktop/Settings/touch andkeepSEN297 forbinary. State log/host/SEN297/continuation.json. Historical entries follow.

2026-11-16 SEN297 continuous SSC/native owner trial prepared.87of89objects unchanged vsSEN296; onlySensorHub/RawSource updated. Owner+independent HID/CoreMotion observer signed; clock/control/nativepipeline offline passed. Protectslot1/span8 UUIDa513b46db77a4843805e2c1b0e9f6b42 untilfull512MiB recovery. Not deployed yet; native/axes/fusion/ALS hardwarepending. State log/host/SEN297/continuation.json. Historical entries follow.

2026-11-16 SEN296 ACCEPTED afterlongLogo delay: userdesktop/Settings/touchPASS;806binarysamples206/206/393/1 matchkernelallfields,dropped0,4stop;SSC18/18/errors0 fullshutdownretained0. Full512MiB/4970168valid collected-clear/readback bootunchanged,AndroidUSB/nooccupiedslot. SpringBoardmain213.69475sgap startsbeforeSensorworker; exactwaitcauseunproven, donotmodifyacceptedparts. Nextnativeclock/axes/continuousconsumer+CoreMotion/rotation/ALS. State log/host/SEN296/continuation.json. Historical entries follow.

2026-11-16 SEN296 duplicateRawclass fix deploying. Manualconstructor/prepostremoved, OSRuntime auto1 retained; 89objects/88unchanged(inclRAMbyteidentical),21overlays/loaderpassed. Protectslot1/span8 UUIDf97965425ea84c5383876e678b7e0f70 untilfull512MiB recovery. Actualbinarysampling/desktoppending; acceptedpartsunchanged. State log/host/SEN296/continuation.json. Historical entries follow.

2026-11-16 SEN295 FAILED Logo; full512MiB/2233352valid collected-clear/readback bootunchanged. PROVEN duplicateclass: dictionary returns exactRawSource metaclass0xfffffff02b98ecf8, then0xfffffff007b70fe8 duplicatepanic. DataBlock __mod_init_func alreadyregistered; worker repeatedconstructors/postModLoad. AndroidUSB/nooccupiedslot. Fix ONLYmanual secondregistration; acceptedcomponents unchanged/no defensivecode. State log/host/SEN295/continuation.json. Historical entries follow.

2026-11-16 SEN295 temporaryboot succeeded,60sUSBsyslog3264462B saved; pairedlockdownmux timedout,no binaryretrieved. Physicalstate feedbackpending; do not presumehang. Protectslot1/span8 UUID597b7c19fb9b476589a323c2b7c91ba5 untilfull512MiB recovery. Alreadyrepairedparts remain unchanged peruser. State log/host/SEN295/continuation.json. Historical entries follow.

2026-11-16 USER reiterates acceptedcomponents must remain inuse unchanged. Preserve repaired keyboard/touch/display/GPU/WLAN/backlight/multirangeRAM implementations; only edit actual active sensorfault scope. No defensive programming.

2026-11-16 SEN295 registration-internal trace deploying. Original275instructions/22calls retained+45milestones inRawSource-onlycopy, originalpostModLoad untouched; scalarregisterreplay/21overlays/loaderpassed. Protectslot1/span8 UUID597b7c19fb9b476589a323c2b7c91ba5 untilfull512MiB collection. No claimedfix ornewdefense; SEN292 remainsacceptedbaseline. State log/host/SEN295/continuation.json. Historical entries follow.

2026-11-16 SEN294 FAILED user systemhang afterdesktop. Full512MiB/3199447valid collected-clear/readback bootunchanged; syslog9500191B saved; AndroidUSB/nooccupiedslot. RAW INIT untimestamped milestones found: lock/preModLoad/constructors returned, lastpostModLoad enter; oldprefixfilter omissioncorrected. Needactualregistration cause, noSLPI/SSC thisrun. No defensive programming. State log/host/SEN294/continuation.json. Historical entries follow.

2026-11-16 SEN294 trace temporaryboot succeeded after588byteargs/kernel/slot binding. NativeUSBcapture78003 pending; physicaltrace resultpending. Protectslot1/span8 UUID38180fd8d5424a12946a4c401cc2b1a7 untilfull512MiB collection. OnlyRawSource initialization milestones added; no claimedfix/no defense code. State log/host/SEN294/continuation.json. Historical entries follow.

2026-11-16 SEN294 class-init trace candidate preparing/deploying afterSEN293 hang. OnlyRawSource.o addsfunctionentry andIOLockAlloc/preModLoad/constructors/postModLoad beforeafter persistentmarkers; SensorHubcore-r10 and87otherobjects reused. Kernel-r11-final-return-trace valid21overlays/loader; earlier r11-return-trace isstale DO NOTuse. Protectnewreservation untilfullrecovery. State log/host/SEN294/continuation.json. Historical entries follow.

2026-11-16 SEN293 FAILED: user systemhang20:05 afterdesktop;60sUSBsyslog8366271B thenUSB disappears. Full512MiB/3038261valid collected-clear/readback bootunchanged;AndroidUSB/nooccupiedslot. Worker-start87.350975 then newrawclasses init neverreturns; noSLPI/SSC/rawsamples thisrun. No provenexactdeadlock/SIMDcause; need trace IOLockAlloc/preModLoad/constructors/postModLoad. PreserveSEN292 acceptedbaseline, no defensive programming. State log/host/SEN293/continuation.json. Historical entries follow.

2026-11-16 SEN293 fastbootboot succeeded; capture33654 waits nativeUSB. KeepSEN293 untilAFCbinary retrieved; physicaldesktop/Settings/touch pending. Protectslot1/span8 UUIDd7e675f07ed54cc38d5b4a0c4efb9cd5 untilfull512MiB recovery. BinaryRawSource/rootcollector actualruntime unverified. State log/host/SEN293/continuation.json. Historical entries follow.

2026-11-16 SEN293 binaryrawsource/rootcollector deploying. OnlySensorHub replaced+RawSource added;2048queue retainsfinishedsamegeneration, noMachstamp/nativeHID. Collector signed/rootlaunch; stopsafterfinitecapture and writesMedia/NabuSensorHub/SEN293.bin+json.3modes809retention/nativepipelinepass,21overlays/loaderpass. Freshslot1/span8 UUIDd7e675f07ed54cc38d5b4a0c4efb9cd5 protectuntilfull512MiB recovery; needAFCbinary BEFORE Androidrecovery. State log/host/SEN293/continuation.json. Historical entries follow.

2026-11-16 SEN292 fully collected512MiB/4352095valid,clear/readback and bootpartitions unchanged; userdesktop/Settings/touch PASS. Raw kernel809(207/207/394/1), completeCSV808(gyrooneIOLog line interleavedBluetooth, nofabrication), SSCerror0 cleanupretained0. Timer4/4, fixeddeadline fire+301tick=15.677us, callback+178704tick=9.3075ms, disable2success,noerrors, conditionalcompatible1;11rawQMI saved, SSCsampleepoch/nativeMotion NOTqualified. AndroidUSB/nooccupiedslot. Nextdirectraw/nativeintegration; no defensive programming. State log/host/SEN292/continuation.json. Historical entries follow.

2026-11-16 SEN292 nativeUSB60s capture saved8855875B; physical desktop/Settings/touch and Android recovery feedback pending. Keep slot1/span8 UUID6685a2620ada46a6a86100c8bc90294d protected untilfull512MiB collection. Timer/fourchannel results await canonicalrecovery; noSSCepoch/nativeMotion claim. State log/host/SEN292/continuation.json. Historical entries follow.

2026-11-16 SEN292 temporaryboot command succeeded afterdeployment/readback/actual588byteargs binding. Capture60458 waits nativeUSB then60s; physical/currenttimer/raw4channel results pending. Protectslot1/span8 UUID6685a2620ada46a6a86100c8bc90294d untilfull512MiB recovery. No nativeMotion/SSCepoch claim; no defensive programming. State log/host/SEN292/continuation.json. Historical entries follow.

2026-11-16 SEN292 deploying: freshslot1/span8 UUID6685a2620ada46a6a86100c8bc90294d reserved/readback, protectuntilfull512MiB recovery. Fixeddeadline timer+raw4channels, onlySensorHub changed fromSEN291 linkselection. User forbids defensive programming. State log/host/SEN292/continuation.json. Historical entries follow.

2026-11-16 user reiterates: do not add defensive programming. SEN292 timer integration built: fixedAPVirtual+1s deadline, predeclared1ms read/200ms callback policies, separateQRTR0x101 vsraw0x100, fulltimerQMI/APbrackets+residuals; noSSCepoch/nativeMotion claim. OnlySensorHub object changed fromSEN291 finalselection;20timer casesx3,ARM64 scalar/MRS/final21overlays/loader passed. Newreservationpreparing; state log/host/SEN292/continuation.json. Historical entries follow.

2026-11-16 SEN291 fully collected512MiB/4087222valid; clear/readback and bootpartitions unchanged. User desktop/Settings/touch PASS; raw206/206/393/1=806, SSC18/18 disable4 error0, cleanup retained0.808 actualAP/Mach brackets valid19.2MHz, one segment, both offsets0..0,max35ticks; SSCepoch NOTverified/nativeMotion NOTconnected. AndroidUSB/nooccupiedslot. NextSEN292 fixed-deadline timer integration. State log/host/SEN291/continuation.json. Historical entries follow.

2026-11-16 SEN291 temporaryboot succeeded afterdeployment/readback/actual588byteargs binding. Livecapture session18363 waits nativeUSB then60s; physicalfeedback/current4channel/counters pending. Protectslot1/span8 UUID5c44f439ba664898ad088521b38801d1 untilfull512MiB recovery. OnlySensorHub clocks asm changed, noepoch conversion/nativeMotion. State log/host/SEN291/continuation.json. Historical entries follow.

2026-11-16 SEN290 fully collected512MiB/5164440valid, clear/readback and bootpartitions unchanged; user desktop/Settings/touch PASS. Fourrawchannels206/206/393/1=806, SSC18/18 disable4 invalid/foreign/errors0, files3expectedENOENT Access13=0, cleanup retained0. NewclockinstrumentationFAILED: Mach-O semicolon truncatesMRS; fields unassigned, noepoch qualification. SEN291/r8 newlineasm+actualmachinecheck passes object/final,87of88objects identical,21overlays/loader pass. Reservedslot1/span8 UUID5c44f439ba664898ad088521b38801d1; deploying, protectuntilfullcollection. State log/host/SEN291/continuation.json. Historical entries follow.

2026-11-16 SEN290 deployed/readback/actual588byteargs verified. Newslot1/span8 UUIDaa5ab1e1f0224ae8a1e710c8ecfcf99d protectuntilfullcollection. ALS2/4 compatibility allwords+rawAPclock/Mach,87of88objects sameSEN289. Startlivecapture thentemporaryboot; sampling/clock/physical pending. State log/host/SEN290/continuation.json. Historical entries follow.

2026-11-16 SEN290 preparing freshslot afterSEN289 fullcollection/clear. ALS witnessed2or4value compatibility+all4words+selectedSUID and rawMach/APcounter brackets, no epochconversion/nativeMotion yet.20SSCscenariosx3/raw1029replay+original20Bpacket and negativepass.88objects/87SEN289identical, onlySensorHub changed; exactEntry/Controller/RegistryStorage reused. State log/host/SEN290/continuation.json; inspect receipt before repeatedwrite. Historical entries follow.

2026-11-16 SEN289 collected/cleared: desktop/Settings/touch userPASS; registryparent path hardwarePASS Access13=0, files1686/3expectedENOENT. Listener/DMA/fullcleanup retained0.807true3axis(207/207/393), ALS0/invalid1 exactcause valid20B packed4floats/status3 rejected bycount2-only predicate; fullrawpayload preserved.4820995valid/512MiB saved-clear-readback,bootunchanged; AndroidUSB/nooccupiedslot. SEN290 supports ALS2or4 only, preserveall4bits+SUID and rawMach/APclock brackets. State log/host/sensors-20261116/continuation.json. Historical entries follow.

2026-11-16 SEN289 deployed/readback/actual588byteargs verified. Reservedslot1/span8 UUID32dc213de1e74f2fa55ca67d85cce78f protectuntilfullcollection. Registry internalparent fix+ALS issue/rawpayload diagnosis; sameBoot/86of88objects sameSEN288. Physical/live/sampling pending. State log/host/SEN289/continuation.json. Historical entries follow.

2026-11-16 SEN289 preparing freshreservation afterSEN288 full512MiB collected/cleared. Fix11Access13 legitimate internalparent registry paths; retain originalALS contract, add exact issue/rawpayload logging forALS0/invalid1.47fileRPC+18SSCscenarios x3 pass;88objects/86SEN288 identical, onlySensorHub/RegistryStorage changed. No newALS/nativeMotion pass. State log/host/SEN289/continuation.json, inspect receipt before repeatedwrite. Historical entries follow.

2026-11-16 SEN288 collected/cleared: user desktop/Settings/touch PASS; independent listener1693reverse/APFS seed139files PASS, DMA/GLINK/shutdown/off/release retained0.807true rawsamples accel207/gyro207/mag393; ALS0/invalid1,4channel/nativeMotion NOTpassed.11Access13 legitimate registry/registry/../sns_reg_version duecanonical any-parent rejection; fix+ALSpayloaddiagnostics forSEN289.512MiB/4800257valid saved, clear/readback verified,boot partitions same. AndroidUSB/nooccupiedslot. State log/host/sensors-20261116/continuation.json. Historical entries follow.

2026-11-16 SEN288 temporaryboot command succeeded, capture session47231 waitingnativeUSB then60s. Allow2min forfiniteSSC, up to5min forinitialLogo; keepcurrentOS until live capture/physicalfeedback. Device execution/fourchannel samples/nativeCoreMotion not yetverified. Protectslot1/span8 UUIDffa01eec121e4fc88cf162b928c01189 until full512MiB collection. State log/host/SEN288/continuation.json. Historical entries follow.

2026-11-16 SEN288 deployed/readback verified, actual588-byteargs exact. Freshslot1/span8 UUIDffa01eec121e4fc88cf162b928c01189 protectuntilfull512MiB recovery. Bootreport policy inherited afterstage1 prewrite failure;stage2 passed, imagebytesunchanged. Newlistener/files/SSC4channel capture alloffline passed,86of88objects exactSEN287. StartnativeUSBcapture thentemporaryboot; physical/samplingAPFS outcomes pending. State log/host/SEN288/continuation.json. Historical entries follow.

2026-11-16 SEN288 preparing fresh reservation afterSEN287 fullcollection/clear. Independent listener+APFS registry+finite4channelSSC, alloffline normal/ASan/UBSan incl1029rawsamples and crossmoduleFiles pass.88objects/86SEN287 identical; onlySensorHub replaced+RegistryStorage added, exactEntry/Controller reused. No newdevice samples/nativeCoreMotion yet. State log/host/SEN288/continuation.json; inspect preparationreceipt before repeatedwrite. Historical entries follow.

2026-11-16 SEN287 hardware PASS and fully collected: user desktop/touch normal; thirdIRQ sensor bank52/34bitDMA active, FastRPC sensor_pd attach/mmap/munmap/release4calls4replies all0, DSPVA0x180010000, foreign0/invalid0, GLINKerror0, fullstop/shutdown/off/release retained0.512MiB/4499236valid saved,clear/readback verified,boot partitions unchanged. Android USB/nooccupiedslot. Implement fresh listener+files+finiteSSC4channel capture forSEN288; no samples/CoreMotion yet. State log/host/sensors-20261116/continuation.json. Historical entries follow.

2026-11-16 SEN287 temporarily booted after readback/actual588-byteargs check. Capture session66699 waits for nativeUSB then60s. Physical desktop/touch and sensorIRQ/FastRPC result pending; preserve slot1/span8 UUIDfcbadf59a11f4ea2bebb4708164ca144. OnlyController differs vsSEN286, thirdglobalIRQ subscriber fix. State log/host/SEN287/continuation.json. Historical entries follow.

2026-11-16 SEN287 deploying. Freshslot1/span8 UUIDfcbadf59a11f4ea2bebb4708164ca144; preserve until full512MiB collection. SharedIRQ thirdsubscriberfix;86of87objects identical toSEN286. State log/host/SEN287/continuation.json. Historical entries follow.

2026-11-16 SEN287 preparing fresh log reservation afterSEN286 full collection/clear. SharedIRQ capacity2->3 fixes actual thirdsensor rejection; negative reproduction and three-user ASanUBSan pass.87objects/86identical toSEN286, onlyController changes; sensorcode/bootstrap unchanged. Inspect log/host/SEN287/continuation.json and preparation receipt before any repeated writes. DeviceAndroid. Historical entries follow.

2026-11-16 SEN286 collected: desktop/Settings/touch passed, but sensorDMA attach phase3/status10 failed beforeSLPI/FastRPC. OldlinkedCI168 controller binary has2 globalIRQ slots; WLANbank54+Audiobank53 occupy them, sensorbank52 registrar refuses. Full512MiB/5390185valid saved;clear/readback verified,boot partitions unchanged;deviceAndroid/no occupiedslot. Rebuild sharedcontroller thirdIRQ subscriber then repeat sensor runtime. Evidence analysis/sensors-20261116/SEN286-irq; state log/host/sensors-20261116/continuation.json. Historical entries follow.

2026-11-16 SEN286 nativeUSB live:60s syslog8665880B/71260lines and shell completion saved. Physical desktop/Settings/touch feedback already requested but pending; FastRPC outcome needs fullkernel recovery, noSensorHub lines in syslog. Keep currentOS; preserve slot1/span8 UUIDf184d020303a4cec9d1dedebedc8e160. Capture ended successfully, no background waiter needed. State log/host/SEN286/continuation.json; report analysis/nabu-SEN286.md. Historical entries follow.

2026-11-16 SEN286 temporaryboot commanded successfully; desktop/touch and FastRPC hardware pending. User asked wait2min and report desktop/Settings/touch, up to5min forLogo; keep currentOS for live inspection. NativeUSB wait/capture session70719 bounded60s after connection. Preserve slot1/span8 UUIDf184d020303a4cec9d1dedebedc8e160 until full512MiB recovery. Kernel286c6a01a412e2029b5204f6024ae6a78224dfc2e4b82dd61a3105fed32d2b22; actual588byteargs and deployment readback passed. State log/host/SEN286/continuation.json. Historical entries follow.

2026-11-16 SEN286 sensor-PD/DMA qualification deploying. Freshslot1/span8 UUIDf184d020303a4cec9d1dedebedc8e160; preserve until full512MiB recovery. New34bitSID0x5a1/128KiB shared owner, attach/mmap/munmap/release probe; no listener/sample yet.10RPC+21lifecycle scenarios x3 and6DMA scenarios ASanUBSan passed;87objects/85KBD283 identical,21overlays/loader/scalar checks passed. Kernel286c6a01a412e2029b5204f6024ae6a78224dfc2e4b82dd61a3105fed32d2b22; unchangedSEN284 bootstrap. DeviceAndroid. State log/host/SEN286/continuation.json. Historical entries follow.

2026-11-16 SEN285 hardware PASS: desktop/Settings/touch user-confirmed; GLINK both channels open+close,TX35/RX65,error0; QRTR SSC400 instance1 node9/port12 dynamically discovered,19packets/18announcements incl repeats. SLPI ready86.459992s, full exit94.528433s. Full512MiB/7203365valid bytes collected, clear/readback verified, boot partitions unchanged. DeviceAndroid; no occupied slot. Continue fresh sensor-v2 FastRPC/34bitDMA on KBD283; no samples/CoreMotion yet. State log/host/sensors-20261116/continuation.json. Historical entries follow.

2026-11-16 SEN285 temporarily booted after final588-byte args/readback check; GLINK/SSC discovery and desktop/touch NOT device verified yet. User asked desktop/Settings/touch, allow up to5min ifLogo dueSEN284 delay; preserve currentOS for live inspection. Capture session43703 runs bounded60s afterUSB. Preserve slot1/span8 UUID22c940b1cac64545b258f1673ee3a2cc, preparation-r2. Initialpreflight interrupted/no headerwrite; currentAndroidWLAN address changed, stage1 stopped beforewrites, newreadsaved and stage-r2 deployed. State log/host/SEN285/continuation.json. Historical entries follow.

2026-11-16 SEN285 GLINK/QRTR rebuild deploying. Freshslot1/span8 UUID22c940b1cac64545b258f1673ee3a2cc, r2 preparation/readback verified; preserve until complete recovery. Initial preflight was interrupted; read-only header confirmedzero before fresh r2 guard. Kernel f420d965f831f5b4e11193797823f6b999323a28d8b861cb2da56fea75d2e976,87objects/85KBD283 identical;19 GLINK cases x3,scalar/no global ctor,21overlays/loader passed. SameSEN284 bootstrap, no sampling yet. DeviceAndroid. State log/host/SEN285/continuation.json. Historical entries follow.

2026-11-16 SEN284 phase1 hardware PASS: ready84.452995s, stop/shutdown/off/release86.621973s; user desktop/Settings/touch normal after initial Logo delay. Complete512MiB/5697844valid bytes collected, clear/readback verified, boot partitions unchanged; no occupied slot. Device Android. SpringBoard launch222s vsKBD2838.67s;213.53s main-thread log gap endingWiFiManager en0, began beforeSLPI; exact blocked cause unproven. Continue fresh GLINK/SSC on new sensor-v2 lifecycle, no old objects/injections. State log/host/sensors-20261116/continuation.json. Historical entries follow.

2026-11-16 SEN284 temporarily booted; physical desktop/touch and SLPI lifecycle are NOT yet verified. NativeUSB syslog waiter/capture session43354 running bounded; user asked to wait2minutes and report status. Preserve slot1/span8 UUID116fdc691a1a44b48548a7853b8b2552 until full512MiB recovery. Clean KBD283 rebuild,87objects/85byte-identical; new lifecycle only, no sampling/CoreMotion yet. State D:/github-IOS/XIAOMI_PAD5-NABU/log/host/SEN284/continuation.json. Logs1-150 deletion rejected by policy;3339files/9.419GiB still exist. Historical entries follow.

2026-11-16 SEN284 new sensor rebuild: fresh slot1/span8 UUID116fdc691a1a44b48548a7853b8b2552 reserved/readback verified, deploying. Preserve reservation until full recovery. KBD283 baseline:85 objects identical, only entry changed plus newSensorHub;87 total, no old sensor objects/injections. Lifecycle only, no sampling yet. Kernel 52c4014ce07f01382ac39fc3c7caf2a138e4cf27ea01447306de7c63caf0499d. State D:/github-IOS/XIAOMI_PAD5-NABU/log/host/SEN284/continuation.json. Logs1-150 cleanup remains blocked by policy, no files deleted. Historical entries follow.

2026-11-15 KBD269键盘+传感器联合实测准备：89对象combined kernel-r3-return-trace、原生笔键盘bridge、传感器mode4/原版软件融合选择r2已构建，全部离线检查/APFS读回通过。slot1 span8 UUID=d730800c90444bf3a1f23a185a6dccd8已新预留，未回收禁止覆盖；正在部署，实机键盘/传感器尚未验证。RAM268 SCM/多段RAM/亮度/Wi-Fi/1GiB GPU保留；607字节args含NUL，移除启动RAM自测与debug/keepsyms/kprintf。用户要求两项同步，设备仅root操作；状态log/host/KBD269/continuation.json。以下为历史。

2026-11-15 用户要求完成磁吸键盘：当前KBD269实现中，以RAM268通过基线保留SCM/多段RAM/亮度/Wi-Fi/1GiB GPU。正在补USB2平台、提供方xHCI/keyboard接入和单一笔键盘原生桥；入口与构建/启动包脚本已准备，未部署未预留日志槽。代码worktree nabu-app-store，设备材料D:/github-IOS/XIAOMI_PAD5-NABU；状态log/host/KBD269/continuation.json，报告analysis/nabu-KBD269.md。需完整实现+离线验证后临时启动，实际按键/重连/唤醒/笔共用均待验，禁止把parser通过算成驱动完成。以下为历史。

2026-11-15 RAM268已回收收尾：r6 SCM候选桌面触摸/两次唤醒/USB通过；完整512MiB槽和6449104字节有效日志已保存清空，引导分区一致，当前Android USB无占用槽。Modem/ADSP/GPU PAS均成功终态，DPU WAIT无非零timeout/error。6GiB独立测试终态PASS与780条原始记录主机核验完成。用户另报8GiB PASS；新run D1ACAE34…只读APFS checkpoint33535已取回，确证首轮8GiB写读/524288页驻留，最后落盘为反码写4.5625GiB，未得释放/最终PASS，记录为用户通过+终态证据缺失，非失败；RAM266旧8GiB未完成记录保留。下次8G需回Android前AFC保存最终记录。GPU IOVA1GiB，RAM多段保留；状态log/host/RAM268/continuation.json，报告worktree analysis/nabu-RAM268.md。以下为历史。

2026-11-15 RAM268实机：r6 SCM修复候选已临时启动，用户确认桌面触摸/两次唤醒正常，USB配对/GPU ready；MODEM INIT3次、AUTH14次含完整续传成功，Wi-Fi native offer/扫描成功。独立6GiB验证PASS：两轮全写读、4次393216页驻留、整段释放6GiB、memlimit恢复、退出0；780条原始校验记录通过，压缩采样均0，最低free1.765GiB。旧8GiB测试未通过，全RAM长期稳定及ADSP完整日志仍待验。slot1 span8 UUID=75b67c0b29ee45eeb8b175b32dd2cefe仍占用禁止覆盖，等待用户恢复Android回收512MiB；不额外重启Android。状态log/host/RAM268/continuation.json。以下为历史。

2026-11-15 RAM268接续：SCM r2已固定原提交54ef557头文件，完整续传/共享锁/Modem抽样日志；普通ASan/UBSan各13项通过。集成r6-scm-return-trace的84对象/9230直接/3104远分支、9RAM+10继承+2追踪和loader检查通过。新512MiB slot1 span8 UUID=75b67c0b29ee45eeb8b175b32dd2cefe已预留，未回收禁止覆盖；正在部署，实机尚未验证。GPU IOVA1GiB、RAM多段、Wi-Fi保持；不额外完整重启Android。6GiB独立验证App已签名未运行，旧8GiB压测未通过。实时状态D:/github-IOS/XIAOMI_PAD5-NABU/log/host/RAM268/continuation.json。以下为历史。

2026-11-15 最新接续：RAM266/RAM267两个512MiB槽均完整备份清空，引导分区一致，当前Android USB。Android只读APFS reader已取回Data的stress.json（checkpoint33373），路径log/host/RAM266/android-readonly-recovery；PID248/run2081A5C4…，初次write_pattern最后6.75GiB，未进入读回/mincore，无数据不匹配证据，不能将8GiB测试改称通过。RAM266实时10.7953GiB容量/桌面/触摸/Wi-Fi已证，极限压力稳定性未验收。RAM267锁屏故障另有MODEM PAS4缺终态→ADSP PAS1无返回→DPU保存错误的线索；实际旧Modem对象100次interrupted后错误释放metadata，正在离线修SCM会话，尚无新kernel或新预留。RAM builder已支持替换指定对象/增加共享对象，其余参数保持。GPU IOVA1GiB、日志512MiB；不额外完整重启Android。状态log/host/RAM267/continuation.json。以下为历史。

2026-11-15 最新 RAM267：仅用同一RAM266内核/loader/8GiB压缩池改tag恢复旧stress文件，用户报告锁屏即卡住后已恢复Android；无新压力测试指令。完整512MiB槽已回收清空，2872246字节有效前缀，引导分区一致。后台日志仍活动，DPU固定swap115反复报错，需要与RAM266 8GiB高压卡死分开；stress.json仍未取回。正在构建Android有界只读APFS提取器取Data内/mobile/Media/NabuRamProbe，暂无新启动。当前无占用预留槽，状态log/host/RAM267/continuation.json；RAM266基础容量10.7953GiB已证，压力稳定性未通过。GPU IOVA保持1GiB。以下为历史。

2026-11-15 最新 RAM266压力失败：桌面/触摸/USB/Wi-Fi及实时10.7953GiB容量已通过，但独立RamStress r2固定8GiB测试启动进度变化后整机卡死，USB配对同样超时，不能验收稳定扩容。用户已恢复Android，正在完整回收512MiB槽；slot1 span8 UUID=f462c777934b4add99913bd85e1352bd在清空收据确认前不可覆盖。未取得stress.json最终/最后阶段；后续需读取Data内/NabuRamProbe/stress.json并按本轮内核日志定位。r2仅限测试子进程有限memlimit，未改全局策略，不可先归因硬件。状态log/host/RAM266/continuation.json。GPU IOVA1GiB、压缩池8GiB保持；无新候选/无新启动。以下为历史。

2026-11-15 最新 RAM266：RAM265已确认kmem_ptr_range的VA分配失败，完整512MiB已收清。RAM266同一r4/多段loader仅设vm_compression_limit=524288（8GiB压缩池，未限制物理RAM），等价删serial/pen-hover默认参数，保留small_cores_after=0；601字节args。临时启动进入桌面/触摸正常，USB/GPU ready。独立RamProbe已安装，11月15日17:29实时hw.memsize与NSProcessInfo均11591335936字节=10.7953GiB，8核；bootargs逐字匹配RAM266。旧Performance256的performance.json为11月14日旧记录不可采用，其当前版本只写stacks。正构建独立8GiB VM申请/驻留/两轮读写/释放测试，尚未执行。Wi-Fi radio on，连接未确认。slot1 span8 UUID=f462c777934b4add99913bd85e1352bd不可覆盖；状态log/host/RAM266/continuation.json。GPU IOVA保持1GiB，BootServices299.50MiB回收尚未实施。以下为历史。

2026-11-15 最新 RAM265：RAM264照片确认owned=11591335936字节(10.7953GiB)，空闲10877468672字节两轮全bank写/CIVAC/读通过(约14.086秒)，VM管理661952页、洞5635页。随后kmem范围初始化后普通loader_return，桌面未启动；X4为TCR、X5为回调PA，不能当故障码。RAM264完整512MiB槽已备份清空，存储尚未启动所以0条持久日志；Android引导分区一致。现RAM265仅在r3上补两处共24字节返回追踪，保持RAM/1GiB GPU/Wi-Fi，准备部署；新slot1 span8 UUID=00216afc69fe46d7962b2c8d51da5a49不可覆盖。12GiB差额1233.64MiB已分类：Reserved724.81、地图未描述201.13、BootServices299.50、其他8.19；BootServices可回收性未验证，10.80不是最终容量上限。状态log/host/RAM265/continuation.json。以下为历史。

2026-11-15 最新 RAM264：用户已要求开始12G多段内存改造。低地址主窗口loader-r1与RAM kernel-r3已实现，范围交接、VM洞占位、最终physmap排洞、sum/span统计及两轮全空闲owned RAM地址模式/反码+全bank CIVAC测试均已离线检查；9 RAM跳转与10旧GPU/亮度入口独立审查通过。已部署读回并成功执行临时fastboot boot，尚未观察到原生USB，等待物理反馈；实机容量与RAM TEST PASS均未验收。新512MiB预留slot1 span8 UUID=00bf8da5bab94636bd0f4b906cbf8f6d，未回收前禁止覆盖。LOGRAM263未启动预留已完整512MiB备份清空，旧收据已失效。GPU IOVA保留1GiB、Wi-Fi配置保留。唯一实时状态log/host/RAM264/continuation.json；源码patches/nabu-ram和nabu-ram-loader。以下为历史。

2026-11-15 最新 LOGRAM263：512MiB持久化日志已准备并部署读回，slot=1 span=8 UUID=b83a84ca978d481ab220e2b8b252cfff，尚未启动，设备Android USB；新预留区不可覆盖。配置生成参数已由622缩至606字节（含NUL607/608），实际stage会拒绝超长参数。WIFI262完整64MiB槽已收清；旧trial24的640MiB备份保留并经核对清理旧extent。GPU IOVA保持1GiB，Wi-Fi真实MAC/原生服务保持。RAM原因已确认有效loader只选最大连续块7956MiB，另3099.203125MiB分散空闲；约10.796GiB为当前地图候选合计，非已启用容量。多段交接/内核映射/页管理尚未实现；中央笔迹局部闪烁和持续绘制掉帧仍待修。状态log/host/LOGRAM263/continuation.json；报告analysis/nabu-current-ram-20261115.md、nabu-LOGRAM263-log512.md。以下为历史。

2026-11-15 最新：用户要求持久化日志扩到512MiB，并排查12GiB硬件为何XNU仅7956MiB；GPU IOVA继续1GiB。WIFI262已回Android，64MiB槽完整备份/14644655字节有效前缀并清空读回；日志槽写满，最新持续绘制GPU快照虽有成功回执但详细begin/end缺失。Wi-Fi开关/IP恢复；初始桌面流畅，但中央笔迹局部闪烁、持续绘制变慢仍未修好。20秒58760条trace零丢独立保存。RAM已查明有效loader上限12GiB，只选最大连续区；另3014MiB独立空闲区未纳入，XNU早期页分配同样为单段。正在配置日志span=8并处理已有备份的第24轮旧预留区；当前无新iPadOS启动。状态log/host/WIFI262/continuation.json、log/host/LOGRAM263；报告analysis/nabu-WIFI262-pen-flicker.md及nabu-current-ram-20261115.md。以下为历史。

WIFI262接续（2026-11-15最新）：用户要求GPU上限先保留1GiB，未实施2GiB。GPU261笔小闪后恢复、无卡死，但全局掉帧；60秒273586条及桌面20秒156402条trace均零丢，全轮无OOM/回收触发，不能宣称回收修复有效。桌面GPU均9.673ms、DPU请求到接受18.936ms，最高76.5C未热限频、675MHz回读正常，该数据来自GPU261。GPU261日志64MiB/12843953字节已收清，引导分区一致。WiFi关闭根因：继承PEN259的stage命令漏wifi-mac-file与wlan-native-service，BL260同样遗漏；WIFI262已补真实MAC/原生wlan节点，部署回读并临时启动，native en0/控制器/地址匹配/power=1已确认，原生被动扫描1.7秒返回26 BSS，用户已确认开关正常且能连接，最新en0取得IPv4、RSSI -47dBm，互联网传输未单测；本次开关故障恢复；用户进一步确认WIFI262桌面已恢复流畅、划线仍短暂闪烁，120fps未量测。后续20秒连续画圈58760条trace零丢已导出、syslog4988077字节；用户称在边缘可能越界，不能判定误抬笔，用户随后确认中央也闪且持续绘制后跟不上；最新GPU统计73e14fbcbe524dfea72b663d3cea54a2已完成，等恢复Android回收完整槽分析；报告analysis/nabu-WIFI262-pen-flicker.md。槽1归WIFI262未回收，禁止覆盖。iPadOS实际7956MiB=7.77GiB，Android约11.22GiB可用；本轮handoff给XNU连续0x1f1400000字节，ADT已请求12GiB，旧源文件8GiB限制不代表当前loader，完整12GiB多段映射未处理。状态D:/github-IOS/XIAOMI_PAD5-NABU/log/host/WIFI262/continuation.json；报告worktree analysis/nabu-WIFI262.md、nabu-GPU261-allocation-pressure.md、nabu-current-ram-20261115.md。以下为历史。

GPU261接续（2026-11-15）：BL260两处亮度滑块和两次息屏唤醒通过；笔划线复现局部闪烁后画面冻结。25秒61014条trace零丢，473 GPU任务均完成、501 DPU请求均接受；全轮14265/14265任务、零fault/timeout。原生日志明确backboardd纹理OutOfMemory(Device)，1GiB IOVA窗口高水位1023MiB（不是当前物理用量），1337活BO、驱动cache/pending均0。已回Android，BL260 64MiB槽/11494501字节前缀备份清空，未封口，引导分区未变。普通/linear纹理OOM缺前端导入缓存回收，新增精确OOM释放额外cache引用后单次重试，6项普通/ASan/UBSan、ARM64签名/APFS读回通过；候选worktree artifacts/nabu-allocation-pressure-r1与nabu-bootstrap-GPU261，复用BL260内核与0x35。准备复测，不能宣称闪烁/笔已修复。状态D:/github-IOS/XIAOMI_PAD5-NABU/log/host/GPU261/continuation.json。以下为历史。

BL260亮度实测接续（2026-11-15最新用户顺序）：用户明确“继续修复亮度服务，然后开始真机测试”，并要求不进行防御性编程。本轮在亮度实现及离线检查完成后开始实测，不再等待完整键盘USB2/统一桥；四项其他任务保留。新增真实AppleARMBacklight IOService，nits Q16.16经Android曲线和2048项remap控制KTZ8866；69,817项普通/ASan/UBSan、ARM64完整内核/分支/loader及启动包读回已通过。内核worktree artifacts/nabu-native-backlight-r1，启动包artifacts/nabu-bootstrap-BL260，含笔0x35与正确dirty基线；键盘未接入。准备slot1新日志并部署临时启动，实际状态以D:/github-IOS/XIAOMI_PAD5-NABU/log/host/BL260/continuation.json为准。禁止沿用PEN259旧收据。以下为历史。

Android输入参考接续（2026-11-15最新）：用户确认当前Android模块的笔/键盘体验好、笔无断触漂移。已只读取证Hyper_MagicWindow、内建NVT-ts/xiaomi-keyboard；boot_a五份固件已提取，最近实际加载0x35笔优化版，原iPadOS包0x19。当前sysfs实际pen_update=0、pen_enable=1、keyboard=1，与已加载版本分开记录，之前摘要“三项均1”有误。精确选择分支已从当前内核恢复；独立artifacts/nabu-touch-pen35-reference的16条分区/CRC与原厂解析器全相同。3206:3ffc四份真实描述符117/260/76/25及Generic键位表已取得；接口0键盘ID5共9字节、鼠标ID2隔离；新增NabuHidKeyboard.h普通/ASan/UBSan各4043项与ARM64通过，尚未接USB2/统一桥。报告worktree analysis/four-fixes-20261115/android-input-reference.md；状态log/host/four-fixes-20261115/continuation.json。原生亮度服务、USB2平台/统一桥和最终包仍待完成；0x35未在iPadOS测试，原断触/物理漂移未标记解决。未写设备、重启、部署或采集敲击。继续四项离线完成后统一实测。以下为历史。

四项修复接续（2026-11-15本轮）：正确GPU脏页基线已重建并通过分支/loader检查；修复笔通道重开绕过已解析TIP/压力状态的两项离线复现，补原始帧边沿窗口及mach时间关联，普通/ASan/UBSan与完整ARM64内核/桥构建通过。新内核worktree artifacts/nabu-four-fixes-stylus-display，未部署。用户暂不方便操作；原断触根因和左右物理漂移仍待样本，未猜测校准。用户新供windows驱动/uefi.img已静态分离190个FFS文件/130个ARM64 EFI PE，ACPI和USB2/Display参考报告worktree analysis/four-fixes-20261115/woa-reference.md；不是Windows .sys驱动包。原生亮度服务和完整USB2/HID/统一桥尚未实现，统一包及实测未开始，继续遵守四项出口门槛。状态log/host/four-fixes-20261115/continuation.json；进展worktree analysis/four-fixes-20261115/progress.md。设备保持Android、无新日志槽。以下为历史。

四项统一修复（用户2026-11-15最新要求）：触控笔断触/左右漂移、原生显示亮度连接、已提供磁吸键盘驱动、正确脏页启动包。计划docs/NABU-FOUR-FIX-PLAN-20261115.md，状态log/host/four-fixes-20261115/continuation.json。先固定构建基线，再依次修笔/显示/键盘，最后统一打包；四项实现与离线验证完成后才开始下一真机测试。当前保持Android，可做授权范围内只读ADB取证；不再用只有诊断或缺模块的候选提前启动。PEN259日志已回收清空。以下为历史。

PEN259（2026-11-15）实机与回收完成：用户确认桌面触摸/息屏唤醒正常，笔偏移断触仍在，亮度滑块手指也不能拖动，并感觉卡顿。64MiB槽和3744327字节前缀已备份清空，未封口；Android引导分区一致，设备保持Android，无新测试槽。实际内核display-r2基于reference-268/i4-10多版本对象，前端256。发现GPU dirty Submit编译后因Windows反斜杠/WSL Path.name漏替换，实际仍链接v168提交对象；脚本修复和真实清单回归通过，尚未新构建/实测。完整2048项背光表已从当前Android内核恢复；原生backlight-control服务/availability链仍待接。笔坐标算术正常但边缘覆盖不足，需tip/range边沿原始压力诊断。状态log/host/PEN259/continuation.json；详细报告在worktree analysis/nabu-PEN259.md及nabu-PEN259-kernel-lineage.md。以下为历史。

PEN259（2026-11-15）已部署回读并临时启动，native USB确认16.5/20F66，用户确认进入锁屏/桌面且触摸正常。内核为worktree artifacts/nabu-PEN259-display-r2（76对象/9179直接/3023远分支/52原区间，实际loader与主机检查通过），启动包nabu-bootstrap-PEN259。已接selector66/67原始亮度等级、保留DPU电源通知、加入IOMFBBrightnessLevel Q16.16 nits观测及笔坐标诊断。Android配置为2..500nits，但完整bl_level_remap缺失，不能称滑块或笔边缘已修复。键盘包缺完整实现，未集成；USB采集未枚举磁吸键盘。槽1归PEN259，未回收前不得覆盖/另启；PEN258已完整备份清空。状态D:/github-IOS/XIAOMI_PAD5-NABU/log/host/PEN259/continuation.json，报告C:/Users/buhuo/.codex/worktrees/nabu-app-store/XIAOMI_PAD5-NABU/analysis/nabu-PEN259.md。以下为历史。

完整越狱继续（2026-11-14）：setup build3 已实机将 /var/jb 原子改指原生APFS Data前缀，64项双路径/共享mmap/截断/锁/rename/只读拒写全部通过；基础命令、firmware16.5、Sileo2.5.1、ElleKit0.4.5已安装配置。Sileo真实Data路径注册成功，但用户桌面未见图标，uikittools触发器待处理。旧sileo_setuid检查误用legacy父进程保护helper（iOS13+Sileo实际走persona），apt唯一缺libkrw0-plugin；准备build4移除本机不用的SHSH依赖、运行触发器及独立setuid/自有tweak包验收。可写bindfs候选已编译但因pager签名/锁/namecache结构问题停用，不部署。新内核通用exec注入候选本地构建中，旧i4-10+jailbreak-02设备仍在线、日志槽1未收不可覆盖。Computer Use停用，爱思安装/FairPlay继续暂停。状态log/host/jailbreak-20261114/continuation.json；以下为历史。

完整越狱目标 active（2026-11-14）：设备仍 jailbreak-02 临时 iPadOS，i4-10 内核+i4-12 启动包，槽1占用不可覆盖。Probe build 3 已在开发者模式false下通过root、task_for_pid/内存读写/线程、PT_ATTACHEXC、JIT和DYLD注入。setup build 1/CI43576184745已安装，root将6,527个基础文件解包到Data的/var/db/nabu-jailbreak/procursus；创建/var/jb/var/mobile遇EROFS，未执行包脚本或安装Sileo/ElleKit。根因当前bindfs强制RDONLY/NOSUID且缺写操作，需补真实可写映射和缓存/写回；不能只清标志或返回成功。包输入已审查且依赖原样保留，libkrw/shshd等依赖仍待处理。未有新内核候选，不需恢复Android。详见analysis/nabu-jailbreak-bindfs-rw-20261114.md及log/host/jailbreak-20261114/continuation.json。商店安装通过，Unity Metal修复已审查未部署；爱思安装/FairPlay继续暂停；设备资料D:/github-IOS/XIAOMI_PAD5-NABU；以下为历史。

爱思工作已按用户要求暂停（2026-11-14）。设备Android USB；i4-12日志10,752,462字节/64MiB已收清（未封口），xid28849备份及Checkpoint缓存已保存；PC Frida已全部detach。12已取到原版2829B证书，但PC实测107，四能力字段缺；13仅本地构建未部署、未准备13槽。13缓存rename的原子不覆盖审查问题未解决，恢复任务后先处理；暂停期间不继续修改或设备操作。状态log/host/i4-install-20261113/continuation.json。以下为暂停前历史。

爱思i4-12（2026-11-14）：已临时启动有界时序候选，仅Lockdown两处HWInfo RPC从5秒延至30秒，checkpointd/ATC仍5秒；保持10内核/同一2201key/11其余启动包。54项ASan/UBSan、arm64、APFS/两项读回及独立审查通过，455文件仅timeout库变。先自动查证书，不盲目要求PC重试。12槽1未收禁止覆盖。11日志15,829,436字节和64MiB已收清、xid28625三处备份齐全；PC20次106(本地10106)、六IC-Info实测缺失。原版证书初始化早于FairPlay ready超时且不自动刷新，MCM因果未定；30秒不是已修复结论。PC Frida已detach。Computer Use停用，无提交推送。状态log/host/i4-install-20261113/continuation.json。以下为历史。

爱思i4-11（2026-11-14）：PC实际20次完整sync均106，rq/sig读取和两次HTTP helper均0；原版106唯一来自0xc9响应状态字节，本地映射10106，业务含义未知。57次设备prepare均YES/error0。PC Frida已detach，证据pc-return-summary.json。用户恢复Android，11日志15,829,436字节及64MiB槽已回收清空读回（未封口）；新增只读备份xid28625实测Library/FairPlay整目录及六个IC-Info均ENOENT，原版fairplayOpen本轮三次-42004。不能将106直接命名为缺证书。保持同一2201key、Computer Use停用、无提交推送。

爱思i4-10（2026-11-14）：补原版IOTextEncryptionFamily已跨过注册缺口，鲁大师原版fairplayOpen实测-42004→crypter 0xe00002c1→LOAD_DECRYPTFAIL10→errno80，用户提示需购买账号，尚未执行应用。ATC握手通过，PC后续Keybag同步取消；AF2与FPAirFair数据类不同，不能称覆盖冲突。10日志6,096,808字节/64MiB已收清（未封口），前后fairplayd.A2/iTunes_Control备份齐全；设备Android USB，独立AES2201密钥保持不变。后续2204/3000 Unsupported晚于首次应用失败，未加新key；准备观测实际Keybag client/prepare，无下一候选。Computer Use停用，无提交推送。状态log/host/i4-install-20261113/continuation.json。以下为历史。

爱思i4-09（2026-11-14）：默认关闭本地AES2201实验已实机使原版Capabilities/SyncAllowed/ReadyForSync通过；证书仍MissingValue，爱思自身未确认安装。用户要求排查已安装鲁大师3.2.9闪退：kernel set_code_unprotect=4 / spawn errno85，处于加密可执行加载阶段，正查text_crypter注册。08日志17,520,113字节/64MiB已收清；09前fairplayd.A2与iTunes_Control只读备份齐全。设备09 iPadOS，槽1未收归本任务，必须保留独立2201密钥；Computer Use停用。状态log/host/i4-install-20261113/continuation.json。以下为历史。

爱思i4-07（2026-11-13）：i4-06 TLS已通但用户确认仍0%。新栈确认ATC生成Grappa同步握手/iTunesCloud初始化再次阻塞FairPlay；两库缓存直跳绕过interpose。新候选仅ATC进程私有COW修改四个精确RPC的options/timeout常量，9项主机检查/arm64/APFS读回通过，正在准备临时启动。06完整日志已收清。保留v238内核/GPU246基底，设备槽1归爱思，Computer Use停用。状态log/host/i4-install-20261113/continuation.json。以下为历史。

GPU246（2026-11-13）b51535a/CI43373747206成功，native统计测试、实际源码、iOS目标/签名及APFS读回通过，已临时启动、native USB/GPU ready。待桌面触摸确认后先预热15秒再采样15秒；启用编码/复制来源/Mesa阶段，保留245 Turnip和v238内核。槽1属于246，未回收；245日志已收清，最高72.6°C未限频。目标active；状态log/host/gpu-v246/continuation.json，接续work-summary.md。以下为历史。

GPU245日志已收清（2026-11-13）：13,402,282字节有效前缀和64MiB槽，最高72.6°C未限频；设备Android USB，无需再请求恢复。GPU246 b51535a/CI43373747206仍在构建，尚未准备新槽/部署。CI成功审查并打包后直接准备246槽和临时启动，不额外重启Android。状态log/host/gpu-v246/continuation.json。以下为历史。

GPU246（2026-11-13）b51535a/复制来源与编码专项CI43373747206运行；旧43372297578已请求取消修正DeviceShared调用。31补丁本地还原通过，native/iOS测试待CI，未部署。包脚本仅替换frontend并保留245 Turnip，开启编码/复制来源/Mesa阶段采样，重建runtime需预热。设备GPU245 iPadOS，槽1未回收。接续log/host/gpu-v246/work-summary.md与continuation.json。以下为历史。

GPU245（2026-11-13）复测233555条trace零丢，777接受/0拒绝，765完整输出，最忙整秒110；资源比50.6→2.71，分组组提交CPU约减半，较重画面CA/GPU仍约14–18/16–20ms，120fps未达。第一次前9秒低活动，不作完整滑动对照。完整34行耗时表analysis/nabu-gpu-v245-cs-index.md。设备GPU245 iPadOS，槽1未回收；保留CS去重，下一步合成编码与GPU绘制/复制来源。状态log/host/gpu-v245/continuation.json。以下为历史。

GPU245（2026-11-13）037aa04/专项CI43366595700成功；CS范围索引、实际权限与生命周期检查、iOS目标/签名及APFS读回通过，已临时启动，native USB/GPU ready，待桌面/触摸与15秒测试反馈。GPU244日志10,977,832字节和64MiB槽已收清，最高65.3°C未限频。新槽1属于GPU245，未回收前其他任务不得操作设备/槽。目标全程实际120fps仍active。状态log/host/gpu-v245/continuation.json。以下为历史。

GPU244（2026-11-13）242173条trace零丢，893接受/0拒绝，823完整输出，最忙整秒82；GPU均12.164ms，CA开始→DPU接受均30.326ms，仍未达全程120fps。CS资源44794798/45237374条占99.02%，来源加总一致。GPU245只索引CS精确IOVA/size并合并access，35组语义/51分配失败/40冲突及ASan/UBSan通过，待完整CI和实机。GPU244仍iPadOS，槽1未收，替换前先回收。完整33行耗时表见analysis/nabu-gpu-v244-cs-origins.md，状态log/host/gpu-v245/continuation.json。以下为历史。

GPU243（2026-11-13）223452条trace零丢，792接受/0拒绝，746完整关联输出；GPU均10.829ms，主线CA开始→DPU接受均27.167ms，仍未达全程120fps。已按用户要求提供最大/最小/平均和原因/合理性/优化表，见log/host/gpu-v243/desktop-01/latency-table.md。来源53/54/55误放旧提交分支而实际走async，已披露，不能当来源为0。GPU244源码7225794移至共同入口，CI43362305264运行。设备仍GPU243 iPadOS，槽1未回收；替换前先收日志。243统计请求a9204d461ad34b36a1159e6c4fd5db27的内核快照待收。状态log/host/gpu-v244/continuation.json。以下为历史。

GPU242（2026-11-13）普通set去重未确认性能收益：214501条trace零丢，890接受/0拒绝，最忙整秒86；817输出原始/唯一范围41629943/876972，仍47.47倍，collector0.892ms。GPU CP→RB均10.864ms，CA render CPU8.561ms，全程120fps未达标。GPU241运行日志9416004字节及64MiB槽已回收清空；242仍在iPadOS，槽1未收。GPU243源码7b300b5增加3条提交来源计数，专项CI43359472254运行；复用v238内核/GPU242前端配置，不开Mesa CSV。回Android后先收242日志。状态log/host/gpu-v243/continuation.json。以下为历史。

GPU242（2026-11-13）源码3997d95已推送，Turnip专项CI43357399784正在编译。普通描述符集在每个命令缓冲内只记录一次，避免提交时重复展开；主机等价检查已通过，尚无实机收益。GPU241已完成15秒采样，126999条内核记录零丢、55779328字节CSV已保存；497接受/0拒绝，463个输出精确关联，原始/唯一资源22602431/506956。设备仍在GPU241 iPadOS，持久化槽1未回收；先回Android收日志，再部署GPU242。GPU242复用v238内核/GPU232前端，关闭Mesa CSV/indirect采样，保留675MHz/120Hz/Hall/3drawable/CPU调频。全程实际120fps目标active。状态log/host/gpu-v242/continuation.json；阶段报告analysis/nabu-gpu-v241-command-stages.md。以下为历史。

GPU239（2026-11-13）已从Android只读提取138,768,384字节Turnip CSV（有效非零前缀138,747,904，尾20KiB零及一条截断记录）；8524个完整pass。3,653,511字节持久化日志及64MiB槽1已回收清空读回（未封口），Android引导分区未变。239内核trace未导出，Data中旧frame-trace-1.bin与237逐字节相同，不得用于239关联。CPU调频与GX回读已提交fd7333b。准备GPU240少量阶段时间戳与自动15秒导出，保留v238内核/GPU232驱动、675MHz/120Hz/Hall/3drawable；未准备240槽或部署。状态log/host/gpu-v240/continuation.json。以下为历史。

GPU238日志3,155,604字节及64MiB槽已回收清空读回（未封口），最高64.9°C。GX时钟只读回读：gpu_cc_pll0 mode=d1000005(锁定) L=70 alpha=0x5000→VCO 1350.0MHz，gx_gfx3d RCG cfg=0x101(源1、分频1)，分支0x4221(时钟开)；1350/2=675.0MHz与请求一致（源1按厂商gpucc-sm8150为PLL0二分频输出，未在此重新核对源码；仅上电后读一次）。GPU未被欠频，调频后剩余瓶颈为GPU工作量本身（典型桌面帧CP→RB约8–10ms）和重画面的CA CPU。直接渲染(sysmem)无收益，保持驱动默认。设备Android USB，槽1已清；CPU调频(NabuCpuFreq)与GX回读源码未提交，Turnip范围索引半成品未用。全局实际120fps及两延时目标active；状态log/host/gpu-v238/continuation.json，证据gx-clock-readback.json。以下为历史。

GPU237日志5,541,597字节及64MiB槽已回收清空读回（未封口），最高67.2°C未限频。Android下本机GPU档位257/345/427/499.2/585/675MHz。GPU238=234调频内核对象集仅替换NativeAdrenoA6xxPower.o（enableGx后只读回读gpu_cc_pll0 mode/L/alpha、gx_gfx3d RCG 0x101c/0x1020、分支0x1054），13组OPP主机检查、ARM64编译、66对象链接/分支/加载器检查通过；内核artifacts/nabu-gpu-ready-v238，启动包为GPU232（无编码计时、驱动默认渲染）。已临时启动、GPU ready、无合成报错；回读行早于在线syslog，须回Android后从持久化日志读取。槽1含238日志未回收，其他任务不操作设备/槽。CPU调频与本回读源码均未提交。全局实际120fps及两延时目标active；状态log/host/gpu-v238/continuation.json。以下为历史。

GPU236日志5,305,289字节及64MiB槽已回收清空读回（未封口），最高74.2°C未限频。GPU237=234调频内核+GPU232启动包+backboardd TU_DEBUG=sysmem（无编码计时），与236只差渲染方式：用户称与236相近、画面正常。694755条trace零丢，2527接受/0拒绝，2406输出精确关联；最忙整秒94/94/93，繁忙接受间隔1个VSync占47.4%（236 GMEM为61.9%）。GPU CP→RB均9.829/P50 10.256/P99 20.25ms，2406个中1541个>8.33ms（236为8.897/8.286，355/729）；按每输出原始范围分组GPU均值sysmem/GMEM：1–4万7.44/7.32，4–7万11.69/9.51，>7万14.15/15.22ms。直接渲染无收益，后续保持驱动默认。CA串行均10.79/P50 8.15ms，render CPU均7.83ms。结论：调频后主要瓶颈为GPU执行（典型桌面帧约10ms，675MHz为请求值，实际核心时钟未回读）。设备仍在iPadOS，槽1含237日志未回收，其他任务不操作设备/槽。全局实际120fps及两延时目标active；状态log/host/gpu-v237/continuation.json。以下为历史。

GPU235日志8,815,871字节及64MiB槽已回收清空读回（未封口）；调频全程大核/超大核最高行，最高74.9°C未限频。GPU236=234调频内核+GPU232启动包（无编码计时、驱动默认渲染）：用户称与235相近、画面正常。223874条trace零丢，756接受/0拒绝，729输出精确关联；最忙整秒95/95/90，繁忙接受间隔1个VSync占61.9%（235为53.1%，232为26.1%）。CA串行均9.482/P50 7.525ms，378个迟到帧对中306个CA串行>8.33ms；render CPU均7.166ms（235为8.763，232无调频为9.765）；GPU CP→RB均8.897/P50 8.286/P99 19.42ms，729个中355个>8.33ms，producer等待均6.82ms。负载不同，仅为观测对比。设备仍在iPadOS，槽1含236日志未回收，其他任务不操作设备/槽。全局实际120fps及两延时目标active；状态log/host/gpu-v236/continuation.json。以下为历史。

GPU234实机：CPU调频生效。固件把大核/超大核留在第0行710.4/825.6MHz（L3 1536、小核1632MHz），调频后请求2419.2/2956.8MHz；同一小核循环速度407989→446387（1.094=1785.6/1632）；最高65.3°C未限频。用户确认更流畅但未到120Hz。trace窗口未导出即回Android（无234 trace）；10,354,919字节日志及64MiB槽已回收清空读回（未封口）。内核DPU 120帧窗口活跃均值约67fps（233约46）。
GPU235=234内核+backboardd TU_DEBUG=sysmem，用户称与234相近、画面正常。646199条trace零丢，2119接受/0拒绝，1841输出精确关联；最忙整秒92/90/84（233为55/52/46），繁忙接受间隔1个VSync占53.1%（233为29.6%）。CA串行(begin→finish leave)均10.145ms/P50 9.297，1378个迟到帧对中1238个CA串行>8.33ms；render CPU7.62ms（draw3.64≈48.5µs/次，endEncoding2.60≈33µs/次），GPU CP→RB均6.93/P99 19.65ms、576个>8.33ms。原始/唯一范围仍约62倍（87146211/1377177），tile循环不是重复范围主因；源码确认非push描述符集每次绑定都追加、提交时整集resources重复拷贝。设备仍在iPadOS，槽1含235日志未回收，其他任务不操作设备/槽。全局实际120fps及两延时目标active；状态log/host/gpu-v235/continuation.json。以下为历史。

GPU234加入CPU调频：GPU233日志6,738,189字节及64MiB槽已回收清空读回（未封口）。Android分核基准：同一去重收集18,688条在A55@1785.6MHz/A76@2419.2MHz/超大核@2956.8MHz为46/12.9/10.3ns每条，iPadOS合成线程实测约42–53ns每条；内核无CPU调频（hakios cpufreq为别的SoC的EPSS地址且未启用），大核疑停在固件低频。
新增patches/nabu-power/NabuCpuFreq.{h,cpp}：SM8150 OSM四域(L3 0x18321000/小核0x18323000/大核0x18325800/超大核0x18327800)按负载请求行，TSENS0只读温度上限；nabu-cpufreq=1按负载、2锁高。主机ASan/UBSan测试、ARM64编译、66对象链接/分支/加载器检查通过；内核artifacts/nabu-gpu-ready-v234，启动包沿用GPU233。GPU固定675MHz不变。尚未实机；iPadOS全局实际120fps及两延时目标active。状态log/host/gpu-v234/continuation.json；Turnip命令流范围索引/tile重复转发修正留待下一候选。以下为历史。

GPU233完整iOS前端CI43213656939/9db3887成功并下载审查；编码CPU汇总主机ASan/UBSan/实际wire关联检查通过，启动包APFS及7项读回一致。正准备新槽1并临时启动；回收前其他任务不操作设备或槽。
复用GPU232驱动、230 Rust archive/cache与226内核，保留675MHz/120Hz/3drawable/Hall/原生合成。iPadOS全局实际120fps及两延时目标仍active；状态log/host/gpu-v233/continuation.json，以下为历史。

GPU232实测：276480条trace零丢，983接受/0拒绝、913个输出精确关联；collector均1.351ms/P99 5.938，较231的6.101/29.244下降（负载不同）；CA render CPU9.765ms/GPU P99 14.836ms，仍卡顿，最忙整秒59个新画面接受。
4,217,118字节日志和64MiB槽已回收清空读回（未封口），AndroidUSB。GPU233每命令缓冲编码CPU汇总主机ASan/UBSan及分析关联检查通过，待完整iOS前端重链接；保留232驱动/230 Rust archive与226内核，未准备新槽/部署。iPadOS全局实际120fps及两延时目标active；状态log/host/gpu-v233/continuation.json。以下为历史。

GPU232完整Turnip CI43206168009/43ae84e已成功并下载审查；hash去重46组语义/26分配失败/40项冲突链通过，启动包APFS及7项读回一致。正准备新槽1并临时启动；本轮日志回收前其他任务不操作设备或槽。
复用230前端/runtime与226内核，保留675MHz/120Hz/3drawable/Hall/原生合成；iPadOS全局实际120fps、CA总<5ms及整链<8.32ms仍active，尚无232实测。状态log/host/gpu-v232/continuation.json；以下为历史。

GPU232源码43ae84e，hash去重后仅排序唯一范围；46组语义/26个分配失败清理点/40项冲突链及ASan/UBSan通过。完整Turnip专项CI43206168009运行；复用230前端/runtime和226内核，未准备新槽/部署。状态log/host/gpu-v232/continuation.json，真实全局120fps与两延时目标active。

GPU231用户更正为仍卡顿；402159条trace零丢、1490接受/0拒绝，1271输出driver精确关联。35517385原始范围去重为663500；collector平均6.101ms/CPU5.991ms，原生IOKit0.252ms，Group7.295ms。下一步验证hash去重后仅排序唯一范围。
4,726,770字节日志与64MiB槽已回收清空读回（未封口），AndroidUSB。GPU232本地开发中，未准备新槽/部署；两延时/真实120fps目标active。状态log/host/gpu-v231/continuation.json；以下为历史。

GPU231 Turnip专项CI43197971609/0499165成功，13组资源语义/17个分配失败清理用例通过；下载审查完成，68,177,920字节启动包APFS及7项文件读回通过。正准备新槽1并临时启动，回收前其他任务不操作设备或日志槽。
只替换Turnip重复范围处理和提交计时，复用230前端/runtime与226内核，保留675MHz/120Hz/3drawable/Hall/原生合成。两延时目标仍active，尚无231实测；状态log/host/gpu-v231/continuation.json。以下为历史。

GPU230-r2已采242477条trace零丢，1067次DPU接受/0拒绝；943个输出writer/runtime批次精确关联，group_submit平均8.640ms/CPU8.560ms，wait→批次仅0.023ms、解析/plan/prepare各约0.02ms。用户仍明显卡顿；转Turnip/原生提交资源处理，非Rust调度唤醒。
首启动USB unsupported speed导致pump停止，无性能trace；5706197字节/64MiB已收清；同候选r2USB正常，5597890字节/64MiB也已收清读回（均未封口），AndroidUSB。GPU231准备Turnip重复范围优化与精确提交计时，不改Rust/内核；未准备新槽/部署。两项目标active；状态log/host/gpu-v230/continuation.json。以下为历史。

GPU230完整CI43184629696/0c53d3c成功；runtime提交资源解析/依赖规划/组提交分段及前端→runtime身份边已构建，真实Apple接口/ARM64检查通过，启动包APFS/10项读回通过。正准备新槽1并临时启动，回收前其他任务不操作设备或日志槽。
保留226内核/675MHz/120Hz/3drawable/Hall/原生合成，先预热再15秒操作；两项目标仍active，尚无230实测。状态log/host/gpu-v230/continuation.json。以下为历史。

GPU229预热后OS仍卡顿；195042条trace零丢、787/787合成接受、0拒绝。650次runtime waitScheduled均值11.262ms，CA render CPU7.950ms；597个同输出writer证明等待主要在GPUAccepted之前，非前端group等待（0.00455ms）。QoS线程请求/读回及CA127能力实机确认。
4,133,498字节连续日志及64MiB槽1已回收清空读回（未封口），Android USB；准备GPU230细分submit_batch/资源解析/依赖规划/实际Vulkan提交，未准备新槽或部署。两延时目标仍active，详见analysis/nabu-os-submission-v229.md和log/host/gpu-v229/continuation.json。以下为历史。

GPU229完整CI43178786624(e6b10f3)成功：重编iOS QoS runtime/前端及127能力组合CA观察库；68,177,920字节启动包APFS/10项读回通过，正准备新槽1并临时启动。回收前其他任务不操作设备或日志槽。
保留226内核/675MHz/120Hz/3drawable/Hall/live identity及228原生合成；先预热新shader缓存再测OS，未有229实测结论。两延时目标仍active；状态log/host/gpu-v229/continuation.json。以下为历史。

GPU228已完成桌面/控制中心交互，用户仍明显卡顿。原生GPU合成1375/1375提交接受、0多层拒绝；双INTF119.998Hz不等于120个新画面。render均值11.607ms/CPU11.245，finish14.231ms/CPU0.568，长等待在GPUAccepted之前；详见analysis/nabu-os-composition-v228-chain.md。
20,476,114字节连续日志及64MiB槽1已回收清空读回（未封口），Android USB；stats请求59ac993ec4af40848ad21b34ceb5e058完整、0畸形。GPU229正在修正runtime只对macOS设置QoS而遗漏iOS的问题，并加原版flush/前端commit-scheduled分段计时；尚未准备新槽/部署。保留228原生合成、226内核/675MHz/Hall/120Hz/live identity，不额外重启Android；两延时目标和OS流畅度均未达标。FrameBench1.5仍未安装。以下为历史。

用户新增OS刷新率/肉眼卡顿检查。硬件双INTF各自约120Hz且非双60相加，但227r3菜单44.728秒5370请求全部ExtraLayers拒绝、Accepted0；原版不自动在SwapEnd失败后重合成。GPU228只给225组合包的backboardd加CA_DISABLE_DETACHED=1，原生GPU合成候选APFS/10项读回通过；复用226内核，正在准备新槽1/临时启动，其他任务不操作设备或槽。
GPU227窗口3零丢878520条、1800/1800、lowLatency=true：CA平均3.306ms但897帧>5；整链15.267ms全超标；严格900快/慢交替，i-1占首VBlank。23,896,803字节日志及64MiB槽已回收清空（未封口），AndroidUSB。App1.5双缓冲独立对照8e8d3d2/CI43169666880已成功，未安装；先验OS桌面。状态log/host/gpu-v228/continuation.json；两延时目标active，合成路径输入/输出surface不同，旧直接关联分析器不得盲用。

GPU227复用已验226内核/225启动包，准备原生「低延时定位（15秒）」专项：普通present默认4ms经0.5ms补偿形成3.5ms，lowLatency原生分支可取消默认duration。正在准备新槽1/临时启动，回收前其他任务不操作设备或槽；状态log/host/gpu-v227/continuation.json，两项目标仍active。

GPU226默认15秒1800/1800匹配、120/s、0nil/0fail，CA5.363ms/整链15.204ms，仍未达标；新画面接受连续每次双INTF+1，空层不再重扫。9,688,127字节连续日志及64MiB槽1已回收清空读回（未封口），Android USB。
新证据：1800/1800提前flags1准入已成功，但该次更新target=now早于App sample时间，提前更新未选中新sample；原last_busy→retire4.28ms只是相关性，非连续准入失败。正在追原版目标时刻/选择门禁，未准备227新槽/部署；状态log/host/gpu-v226/continuation.json，两项目标active。以下为历史。

GPU226已临时启动，原生USB上线；槽1含本轮日志未回收，其他任务不得操作设备或槽。等待桌面触摸/菜单反馈，随后仅15秒默认诊断；两项延时仍待实测，状态log/host/gpu-v226/continuation.json。

GPU226完整CI43161154321成功，65对象链接/实际ARM64分支/加载器检查通过；正在准备新槽1并部署临时启动，回收前其他任务不操作设备或日志槽。
复用225组合timer/observer，保留675MHz/120Hz/3drawable/Hall/live identity；两项延时目标仍active、尚无226实测结果。状态log/host/gpu-v226/continuation.json。以下为历史。

GPU226提交8248da5，完整kernel CI43161154321(macos-15-intel)构建中；原位空层所有权交接10组FIFO/24组flip/19组生命周期+ASan/UBSan和ARM64通过，独立review无阻断。
保留225组合timer/observer启动包，clear只交接owner不重map/flip/释放scan资源，新增56独立逻辑事务标记；225日志已收清，Android USB，未准备226新槽/未部署。两项目标active；状态log/host/gpu-v226/continuation.json。以下为历史。

GPU225默认15秒1200/1200匹配、80/s、0nil/0fail；CA5.483ms/整链23.602ms，未达标且性能回退。已证single-free-page=1/6slots/trace63；每2帧插入一次空layer1 clear的同表面硬件reflip，额外占刷新。
已回收7,590,365字节连续日志及64MiB槽1并清空读回（未封口）；用户恢复Android USB。GPU226实现FIFO内无硬件变化的clear所有权交接，保留活跃读租约/mapping；未准备新槽/部署，状态log/host/gpu-v226/continuation.json。以下为历史。

GPU225已临时启动，原生USB/GPU ready，用户确认桌面触摸正常且FrameBench菜单打开；默认15秒trace窗口1已开启。槽1含本轮日志，其他任务不得操作设备/槽；尚无225性能结论。
状态log/host/gpu-v225/continuation.json；两项延时目标active。以下为历史。

GPU225提交32f32b8，专项CI43158743390成功；108旧调度+153准入+72安装/ASan/UBSan及ARM64通过，独立review无阻断。组合timer/observer启动包APFS/6项读回通过，正在准备槽1并临时启动；回收前其他任务不操作设备/槽。
复用223内核/675MHz/120Hz/3drawable/Hall/live identity。仅对原can false且next全空重试原flags1，不改真退休；两项延时目标待实机。状态log/host/gpu-v225/continuation.json。以下为历史。

GPU224默认15秒1800/1800全关联，CA5.407ms/整链15.202ms，仍未达标；640249条trace零丢失。已回收22,890,487字节连续前缀和64MiB槽1并清空读回（日志未封口）；用户已恢复Android USB。
GPU225正在实现受限原版单空闲页准入：CA原有3页，next空闲但普通can为第二页退休而拒绝。保留真实SwapWait/读租约/队列与223内核，不增缓冲；合并timer+observer构建。未准备新槽/未部署；动态状态log/host/gpu-v225/continuation.json。以下为历史。

GPU224已临时启动、原生USB在线，用户确认桌面/触摸正常且FrameBench菜单打开；槽1含本轮日志，其他任务不得操作设备/槽。a714855/专项CI43155459839通过，原生base timer+VSync keepalive已部署，保留223内核/观测和222缓存。
即将默认15秒验证CA总<5ms与整链<8.32ms，目前尚无224性能结论。状态log/host/gpu-v224/continuation.json。以下为历史。

GPU224已实现原版base timer处理立即context commit，并保留原VSync keepalive/锁序；108组ASan/UBSan及ARM64编译通过，准备专项CI。复用GPU223内核和63能力观测，保留222缓存、675MHz/120Hz/3drawable/Hall/live identity。
GPU223已回收6,866,334字节及64MiB槽并清空，AndroidUSB。直接门禁确认1800/1800 target尚在未来约4.25ms；CA5.445ms/整链15.202ms仍未达标。未准备224新槽/未部署；状态log/host/gpu-v224/continuation.json。以下为历史。

GPU223已临时启动，原生USB在线；槽1含本轮日志未回收，其他任务不得操作设备或槽。内核770c687/43150451606和观测6356c36/43151607203均成功，链接/加载器/APFS通过，保留222能力缓存与675MHz/120Hz/3drawable/Hall/live identity。
等待桌面触摸/菜单确认后仅一次低延时15秒，采直接target门禁与整链；CA<5ms和整链<8.32ms仍未达标。动态状态log/host/gpu-v223/continuation.json；以下为历史。

GPU223内核CPU补点CI43150451606进行中；即时更新观测6356c36/CI43151607203成功，启动包APFS/6项读回通过，保留GPU222能力缓存。未准备新槽/未部署，AndroidUSB。
用户目标同时要求CA段总<5ms、App提交至DPU硬件接受整链<8.32ms。GPU222按原场景结束标记已全关联1800/1800：默认5.326ms/15.120ms，硬件接受间隔8.33345ms；两项目标仍未达标。动态状态log/host/gpu-v223/continuation.json；以下为历史。

GPU222默认/低延时15秒均1800提交完成（120/s应用提交），画面触摸正常。缓存使CA主体6.52→0.223ms，总路径5.326/5.455ms，5ms总目标仍active；即时can flags均0。
已回收8,609,515字节连续日志及64MiB槽并清空读回，Android/USB；未准备下一槽。继续原版CA时相/target门禁分析，状态log/host/gpu-v222/continuation.json，设备仍归GPU。以下为历史。

GPU222能力查询缓存已临时启动，原生USB在线；槽1含本轮日志未回收，其他任务不得操作设备/槽。CI43148373620及APFS/6项读回通过，复用221内核。
等待桌面触摸/FrameBench菜单反馈，然后仅15秒默认诊断；总耗时5ms尚未达标，动态状态log/host/gpu-v222/continuation.json。以下为历史。

GPU221默认/低延时15秒均动画触摸正常；总路径13.24/17.06ms，make_buffer_current6.35/6.61ms。已回收20,181,657字节连续日志及64MiB槽并清空读回，Android/USB。
GPU222仅缓存Metal设备真实supportsFamily结果；961da7d/CI43148373620，复用221合格内核。未准备新槽/未部署；5ms是总耗时目标，保留675MHz/120Hz/3drawable/Hall/live identity，不额外重启Android。
动态状态log/host/gpu-v222/continuation.json；以下为历史。

GPU221已临时启动，原生USB/GPU ready/桌面触摸正常，FrameBench1.4安装。默认15秒1521提交完成（101.4/s），0nil/0fail；502007条trace无丢失已导出。1520帧关联present→CA6.59ms/render6.52ms/finish→DPU0.12ms，总13.24ms。
已定位make_buffer_current占6.35ms，collect仅0.006ms；正在同boot低延时15秒窗口2对照。槽1含本轮日志未回收，其他任务不得操作设备或槽；5ms目标active。
状态log/host/gpu-v221/continuation.json；以下为历史。

GPU221提交a3bac6a：partial clear继承layer0真实扫描并转移原read/display-use；24组实际flip、9组FIFO、19组生命周期通过。read范围归并18组及Scheduler/Display ARM64通过。
完整内核CI43143784319运行；用户态c53b201/CI43142617452已成功，context观察启动包APFS及6项读回通过（capability31）。设备Android/USB、GPU220日志已回收清槽，221未准备新槽/未部署。
保留675MHz/3drawable/Hall/120Hz/live identity，不额外重启Android；5ms目标active。状态log/host/gpu-v221/continuation.json；以下为历史。

GPU220已回收5,904,778字节连续日志和64MiB槽，清空读回通过；设备Android/USB。首次15秒900提交完成（60/s）但trace错窗；第二次空layer1清理后CA页推进、driver旧swap保持active形成循环，约3s后drawable_texture_nil，性能未通过。
GPU221正在修复partial clear继承layer0的真实扫描事务；同时read范围归并18组/ARM64通过，CA实际MetalContext CPU约7ms再拆collect/make_buffer。保留675MHz/3drawable/Hall/120Hz/live identity，不额外重启Android；未准备新槽/未部署221。
状态log/host/gpu-v220/continuation.json；设备继续归GPU，5ms目标active；以下为历史。

GPU220完整内核CI43138438550成功（32ed2a5），65对象/分支/加载器通过；render观察用户态194e69b及CI43140019560通过。准备仅替换CA观察库的启动包，再新槽/临时启动/15秒实测。
真实退休后同VSync通知、线程CPU计时、实际render和context类型均进入本轮；5ms仍未达标。设备Android/USB、Data197、槽已清，归GPU；保留675MHz/3drawable/Hall/120Hz/live identity，不额外重启Android。
状态log/host/gpu-v220/continuation.json；以下为历史。

GPU219已回收9,574,832字节连续日志和完整64MiB槽，清空读回通过；Android/USB、Data197。626帧确认旧swap退休晚于CA查询约0.33ms，再等7.83ms。
GPU220真实退休后再发同一VSync已实现；19组生命周期、20组翻帧、7组空层及ARM64通过，正准备完整CI；尚未部署/准备新槽。用户最新目标CA关键路径合计低于5ms，继续仅15秒诊断，保留675MHz/3drawable/Hall/120Hz/live identity。
状态log/host/gpu-v220/continuation.json，目标active，设备归GPU；以下为历史。

GPU219已临时启动、原生USB在线；本轮槽1含日志，回收前其他任务不操作设备/槽。已修复218组包CRLF导致注入丢失的问题，等待桌面触摸反馈及CA安装确认后仅15秒采样。状态log/host/gpu-v219/continuation.json，120fps目标active。以下为历史。

GPU218锁屏触摸无效后息屏：4980641字节日志及64MiB槽已回收清空，Data196、Android/USB。已证原因是父任务启动包inject.conf被Windows写成CRLF，实际解析器保留CR导致input/lockdown/CA库均未注入；触摸硬件1107包有效，CA观察库未加载。
GPU219仅修正inject.conf为LF，6项旧注入+CA项实际init/kernel ASan解析检查通过，启动包APFS/10项读回通过；复用218合格内核。正准备新槽再临时启动，仅15秒采样，不额外重启Android。状态log/host/gpu-v219/continuation.json，目标active。以下为历史。

GPU218 CA诊断已临时启动、原生USB在线；槽1已含本轮日志，回收前其他任务不操作设备或槽。正在等待GPU/CA就绪及桌面触摸反馈，随后FrameBench1.3仅15秒不透明采样。
完整内核43057210415/用户态43057539518及链接/启动包检查通过；保留217原CA环境、675MHz/3drawable/Hall/120Hz/live identity，不额外重启Android。状态log/host/gpu-v218/continuation.json，目标active。以下为历史。

GPU218 CA短诊断完整内核CI43057210415和用户态CI43057539518均成功；65对象链接/分支/加载器和启动包10项读回通过。正在准备槽1并临时启动-v218-ca候选，回收前其他任务不操作设备/槽。
FrameBench1.3为15秒单不透明诊断；保留GPU217原CA环境、675MHz/3drawable/Hall/120Hz/live identity，不启用CA_DISABLE_DETACHED，不额外重启Android。设备当前Android/USB、Data195；状态log/host/gpu-v218/continuation.json。以下为历史。

GPU218按用户要求直接拆约28ms CA等待，已实现IPC40205/40402、present/App、CA更新/SwapWait/End统一有界计时；FrameBench1.3新增15秒诊断，不跑60秒。
首次内核CI43056374920因macOS测试夹具__unused重定义失败，8c078a5已修；新完整CI43057210415和用户态CI43057539518运行中。
下一候选用独立-v218-ca产物，保留217的CA_FORCE_TIMER=1且不启用CA_DISABLE_DETACHED。Android/USB、Data195、日志槽已清；未准备槽/部署/启动。状态log/host/gpu-v218/continuation.json，120fps目标active。以下为历史。

用户最新明确：不跑60秒，直接拆解约28ms CA等待。GPU218原空层修复候选完整CI43051237725及链接已通过但未准备槽/部署；转默认关闭的CA/IPC/present逐段计时与短诊断采样。
下一采样保留GPU217原CA环境复现延时，不启用已准备CA_DISABLE_DETACHED启动包；CA_FORCE_TIMER=1保留。设备Android/USB，Data195，日志槽已清。状态log/host/gpu-v218/continuation.json，120fps目标active。以下为历史。

GPU218提交9c7c619：精确set=clear=2空layer1清理进入同一FIFO，只完成自身无资源事务，保留旧layer0真实退休。7组并发/20组flip/13组生命周期及ARM64通过，完整CI43051237725(macos-15-intel)中。
新启动包仅backboardd环境增加CA_DISABLE_DETACHED=1，原版证据确认回到GPU普通合成；APFS及8项读回通过。CA_FORCE_TIMER=1已确认实际选择原生VSync源，保留。
GPU217日志已保全清槽，Data195、设备Android/USB；218尚未准备日志槽/部署/启动。状态log/host/gpu-v218/continuation.json，120fps目标active。以下为历史。

GPU217已回收9,802,103字节连续前缀及完整64MiB槽，清空读回通过；引导分区未变，Data195，设备Android/USB。日志未封口，不声称覆盖复位前全部输出。
六轮60秒完整、无drawable/命令失败；应用提交41.17/36.47/32.42/25.45/25.13/41.70。硬件不透明CP→RB1.657ms、alpha7.07–7.09ms；零错场景取drawable23.41ms，GPU完成到DPU入口约28.19ms。
正在修复真实set=clear=2的layer1空清理误拒绝，并查CA反馈/真双层合成。保留3drawable/675MHz/Hall/120Hz/live identity，不额外重启Android；状态log/host/gpu-v217/continuation.json，目标active。以下为历史。

GPU217-r2已临时启动，用户确认桌面/触摸正常，原生USB/GPU就绪通过。FrameBench1.2已安装；5秒trace2634条无丢失，50/50硬件CP/RB样本且时钟校准吻合，导出ACK通过。
正等待GPU呈现测试像素/释放验收，再做连续120Hz基准；尚无性能提升结论。槽1含本轮日志未回收，设备仍归GPU217，其他任务不操作设备/槽。
状态log/host/gpu-v217/continuation.json，目标active；以下为历史。

GPU217-r2完整CI43044239183成功；65对象链接/分支/加载器检查通过，最终Mach-O确认VSync第二值continuous、第三值period ticks。
即将重新准备槽1并部署临时启动，旧未启动准备槽已保全清空，不能复用。设备Android/USB、Data194；保留3drawable/675MHz/Hall/120Hz/live identity，不额外重启Android。
状态log/host/gpu-v217/continuation.json，目标active；以下为历史状态。

GPU217尚未部署/启动。合入新发现VSync ABI修复前，已把仅准备未启动的槽1完整回收：runtime0字节、prepared-not-started，清空读回通过。设备仍Android/USB，Data194。
原版证据确认VSync第三64位应为period ticks而非累计sequence；正在修正并重编XNU。trace/helper/cache/App均已CI通过，保留3drawable/675MHz/Hall/120Hz/live identity，不额外重启Android。
状态log/host/gpu-v217/continuation.json，目标active；以下为之前候选准备状态。

GPU217完整XNU CI43039944118、helper43039944107、缓存修复43040953235均成功；65对象链接/分支/加载器与启动包8项读回通过，开始准备新槽并临时启动。
本轮保持3drawable；修复实际DeviceOOM时缓存额外引用回收，加入默认关闭的A64064位时间戳/48MiB trace。GPU216日志已保全清空，Data194，保留675MHz/Hall/120Hz/live identity，不额外重启Android。
设备与槽归GPU217；回收前其他任务不操作。动态状态log/host/gpu-v217/continuation.json，P0–P6目标active，以下为历史。

GPU216已回收22,782,605字节连续日志及完整64MiB槽，清空读回通过，引导分区未变，Data194；设备Android/USB仍归GPU120fps目标。日志未封口，不声称覆盖复位前全部输出。
修正版FrameBench四轮完整60秒：opaque35.83–40.98、alpha41.02应用提交/秒，回调均120Hz；nextDrawable平均23–27ms。第五轮11.19秒encoder/drawable失败，不计作60秒成绩。
累计23700提交/完成、fault/timeout/poison均0；一条交错ranges记录明确丢弃保留原文。正接入A640时间戳/trace并查drawable回收，保留675MHz/Hall/120Hz/live identity，不额外重启Android。
状态log/host/gpu-v216/continuation.json；P0–P6目标active，以下部署状态为历史。

GPU216使用GPU215已验675MHz内核/GPU212启动包，新增FrameBench原生1600×2560持续动画App；专项CI43028487873成功并下载审查。槽1已准备读回，开始临时启动；回收前其他任务不操作设备/槽。
本轮用于定位约100ms供帧与基准吞吐，尚未加入A640硬件时间戳。保持Hall/120Hz/live identity，不额外重启Android。动态状态log/host/gpu-v216/continuation.json，完整P0–P6目标active。

GPU215已回收17,230,082字节连续日志及完整64MiB槽，清空读回通过，引导分区未变，Data193；设备Android/USB。用户桌面触摸正常但仍卡顿。
配对892个GPU任务全部完成，IRQ/fence各892，无新增fault/timeout；累计软件观察完成1.881ms。7个完整DPU窗口840次接受：gap98.452ms、producer0.211ms、present至接受3.433ms；不是纯GPU时间或新画面FPS。
当前用户已授权P0–P6完整120fps目标；继续A640逐帧计时、独立原生分辨率FrameBench与上游约100ms供帧排查。保留675MHz、真实IRQ、Hall/120Hz/共享页直显，不额外重启Android。
状态log/host/gpu-v215/continuation.json，报告analysis/nabu-gpu-v215-runtime-120fps-baseline.md；以下部署状态为历史。

用户最新要求尽快提高真实帧率、直接优化GPU性能，不再长期保守对照。GPU215提交f9ee22c默认原机最高675MHz，配套rawARC320、DDR8363000KB/s；13组真实Power/GMU协议回归及三对象ARM64通过。
GPU214真实IRQ已实测：配对1636次提交/完成及IRQ回调/fence均增加1636，无新增disabled/fault/timeout/poison；用户桌面/触摸正常但卡顿未改善。保留真实IRQ、Hall/120Hz/live identity和GPU212启动包。
GPU214的7473356字节连续前缀及完整64MiB槽已保全清空读回，引导分区未变，Data192，设备Android/USB。末尾256条只覆盖配对15.65%，不能将1.958ms当同场景全段提升。
GPU215沿用完整CI43011757018的合格XNU基底，替换3个GPU对象重链64对象、实际分支及加载器检查通过；槽1已准备读回，正在部署并临时启动，回收前其他任务不操作设备/槽。
原生GPU诊断将显示RequestedGpuKHz/RequestedDdrKBps/StockOppAcknowledged，表示固件确认的请求值。保留Hall/120Hz/live identity，设备归GPU215。状态log/host/gpu-v215/continuation.json；目标active。以下为历史。

GPU214提交0fd535a：GPU完成接GIC332，原10ms轮询只保留SMMU；退出先线程态detach/drain。真实回调/清中断/故障/并发退出回归和4对象ARM64通过。
GPU213实测每次BO映射1.425→0.436ms、index1.211→0.062ms，369次非重叠检查全跳过；桌面仍卡顿。4657952字节及64MiB槽已回收清空，引导分区未变，Data191。
Android参考确认固定257MHz与原机DVFS不同，但499.2MHz对照后置；GPU214保持257MHz、Hall/120Hz/live identity和212启动包。设备Android/USB归GPU214，未准备新槽/部署。
目标active；状态log/host/gpu-v214/continuation.json，以下为历史。

GPU213完整CI43005319897、64对象链接/分支/加载器检查通过，槽1已准备读回，正在部署临时启动。
本轮只改GPU映射CPU索引，保留257MHz、Hall/120Hz/live identity，复用GPU212已验启动包；槽1归GPU213，回收前其他任务不操作。
已保存Android KGSL调度与本机OPP参考；动态调频尚未实施。目标active，状态log/host/gpu-v213/continuation.json。以下为历史。

GPU213提交55e1f07：显示表面物理区间索引排除不重叠GPU新映射，重叠仍走原有精确别名/读租约。13组ASan/UBSan及Scheduler/Publish ARM64通过。
GPU212两次统计完整：449次BO映射639665us，其中index543697us；queue1接收至发出0.100ms、发出至完成观察18.058ms，不能等同纯GPU执行。
GPU212日志4269824字节及64MiB槽已回收清空读回，引导分区未变，Data190；设备Android/USB归GPU213。保留Hall/120Hz，复用212启动包，不额外重启Android。
动态状态log/host/gpu-v213/continuation.json；GPU213未准备槽/部署，目标active。以下状态为历史。

GPU212已进入桌面，触摸正常但连续操作仍卡顿；操作前后GpuPerformance请求均status0且返回匹配编号，统计正文需回收持久化日志确认。
已请求用户恢复Android；槽1含GPU212证据未回收，其他任务不操作。接续先回收，再按GPU提交/完成与DPU明细优化，保留Hall/120Hz。
动态状态log/host/gpu-v212/continuation.json；目标active，以下为历史。

GPU212统计基线：完整CI42996174222、64对象链接/分支/加载器及新助手APFS读回通过；槽1已准备读回，开始部署临时启动。
设备Android/USB归GPU212，Data189；GPU211完整日志已回收清空。本轮取GPU调度/方法统计后按证据优化，保留Hall/120Hz/live identity，不额外重启Android。
动态状态log/host/gpu-v212/continuation.json；本轮回收前其他任务不操作设备或槽，目标active。以下状态为历史。

GPU211提交d928804：新增管理员配对GpuPerformance统计请求，拆分长DPU日志供syslog读取；Display/新producer ARM64及20组翻帧回归通过。
助手CI42987002013及新启动包APFS/读回通过，完整内核CI42987001836中；GPU211尚未准备槽/部署。需替换GPU187旧NativeAdrenoPublish对象为gpu-v211/producer-kernel-check新对象，其他63对象保留。
设备Android/USB归GPU211，Data188；GPU210日志已回收清槽。目标active，保留Hall/120Hz、不额外重启Android，动态状态log/host/gpu-v211/continuation.json。
以下GPU210状态为历史。

GPU210实机桌面/触摸正常但仍卡顿；完整持久化分段证据已回收：3,927,190字节连续前缀和64MiB槽，清空读回通过，引导分区未变，Data188。
模式0退休查询4200次非阻塞/无睡眠无超时；映射和退休各约0.6ms；较短120帧窗口提交间隔43.95ms、端到端15.30ms、producer等待8.36ms。窗口含空闲，不作唯一画面FPS。
下一项测原生GPU调度/提交前耗时，并修复长分段记录仅持久化可见的问题；GPU211未准备/部署。设备Android/USB仍归GPU，保留Hall/120Hz，不额外重启Android。目标active，状态log/host/gpu-v210/continuation.json。
以下GPU210运行记录为历史。

GPU210完整内核CI42983403463、64对象链接/分支/加载器检查通过；槽1已准备读回，开始部署临时启动。
本轮加入桌面分段计时和SwapWait统计，保留生产直显、NC、live identity、Hall/120Hz。槽1归GPU210，回收前其他任务不操作设备/槽。
动态状态log/host/gpu-v210/continuation.json，完整目标active；以下准备阶段为历史。

GPU209桌面DPU直接呈现实机通过；用户无撕裂但仍明显卡顿，性能未通过。共享Metal App 64帧双路像素0错、释放通过；App含125ms主动等待，不能作FPS基准。
8,211,980字节连续前缀及完整64MiB槽已保存清空读回，引导分区未变，Data187；日志未封口，不声称覆盖断电前所有输出。
设备Android/USB归GPU210；真实桌面分段计时与SwapWait统计已实现，ARM64及45组回归通过；提交86a5052已推送，完整CI42983403463中，尚未准备新槽/部署。保留Hall/120Hz、live identity和NC属性，不额外重启Android，目标active。
动态状态log/host/gpu-v210/continuation.json；以下GPU209启动阶段为历史。

GPU208独立接管/IRQ恢复/NC原始翻帧实机通过：用户确认10秒红蓝后桌面/触摸正常，像素/4000页/释放通过。
4,570,623字节连续日志与完整64MiB槽已回收清空读回，引导分区未变，Data186；设备Android/USB归GPU209。
GPU209复用208内核与207启动包，仅nabu-dpu=1、nabu-dpu-diag=0接入桌面；live identity、Hall/120Hz保留。槽1已准备读回，正在部署临时启动；回收前其他任务不操作设备/槽。
动态状态log/host/gpu-v209/continuation.json；完整目标active，桌面与持续高刷新仍待验。以下GPU208运行状态为历史。

GPU208桌面/触摸/GPU ready/Snapshot/普通HaltResume通过；live identity接管5302us且XIN暂停0，独立IRQ及画面/触摸通过。
正在请求NC原始红蓝表面10秒翻帧；槽1未回收归GPU208，其他任务不操作。状态log/host/gpu-v208/continuation.json；完整目标active。
以下部署前状态为历史。

GPU208完整内核CI42976602917、64对象链接/分支/加载器检查通过，复用GPU207已验助手/启动包；槽1已准备读回，正在部署临时启动。
普通DPU slot改为NC，保留live identity、10秒原始表面证据及Hall/120Hz；本轮槽1归GPU208，回收前其他任务不操作。
状态log/host/gpu-v208/continuation.json，完整目标active，不额外重启Android；以下准备阶段为历史。

GPU207原始翻帧仍黑数秒后恢复桌面/触摸，无红蓝；CPU样本10240/错误0、4000页CPU/描述符/页表0差异，10秒前后地址正确。
5,277,593字节连续日志与完整64MiB槽已回收清空读回，引导分区未变，Data185；设备Android/USB归GPU208。
GPU208对照非一致性DMA普通表面的NC叶属性；保留live identity、10秒证据及Hall/120Hz。本地ARM64/页表/20组翻帧回归通过，提交9bbad29已推送等待完整CI；尚未准备新槽/部署，目标active。
状态log/host/gpu-v208/continuation.json；以下GPU207运行阶段为历史。

GPU207桌面/触摸/GPU ready/Snapshot/普通HaltResume通过；live identity接管5386us、XIN暂停0，独立IRQ恢复及两次画面/触摸均通过。
正在请求10秒原始红蓝表面/GOP翻帧，需结合像素/逐页映射/停留地址与用户画面验收。槽1未回收，其他任务不操作设备或槽。
动态状态log/host/gpu-v207/continuation.json；完整目标active，以下部署记录为历史。

GPU207完整内核CI42972474193及helper CI42972474176成功，64对象/分支/加载器/APFS检查通过；槽1已准备读回，正在部署临时启动。
本轮槽1归GPU207，回收前其他任务不操作设备或槽。保留Hall/120Hz，不额外重启Android，目标active。
动态状态log/host/gpu-v207/continuation.json；以下准备阶段为历史。

GPU206已回收10,492,595字节连续日志及完整64MiB槽，清空读回通过，引导分区未变；设备Android/USB归GPU207。
GPU206页表接管与独立IRQ恢复通过桌面/触摸验收；原始翻帧只见瞬间黑、无红蓝，画面未通过。第二次请求在助手退出后未消费。
GPU207增加10秒图案、CPU像素/物理页/描述符/页表及停留期扫描地址证据，取消助手20分钟窗口；本地ARM64/20组翻帧/13组隔离通过，提交358eedd已推送；helper CI42972474176成功，完整内核CI42972474193中，尚未部署/准备槽。
状态log/host/gpu-v207/continuation.json；保留Hall/120Hz，不额外重启Android，完整目标active。以下GPU206运行记录为历史。

GPU206桌面/触摸已由用户确认正常；普通HaltResume通过，halt13us/resume11us、双路/IRQ各新增6、underrun0，halt-audit未启用。
live-identity轮询接管实机通过：5477us且XIN暂停0、4000页/上下文/GOP样本通过，用户确认桌面/触摸正常。
独立ResumeIrq实机通过：IRQ/双vsync各新增7、underrun0，用户确认桌面/触摸正常。
首次FlipGop寄存器/计数/释放检查通过，但用户只见瞬间黑屏、无红蓝，返回桌面/触摸正常；翻帧画面未通过。
第二次请求未被助手消费（AFC文件仍在、IORegistry仍首轮结果），不是第二次硬件翻帧。已请求恢复Android回收完整槽。
槽1已承载GPU206日志且未回收，设备仍归GPU206；其他任务不操作设备/槽。目标active，未暂停。
动态状态log/host/gpu-v206/continuation.json；以下部署前状态为历史。

GPU206完整CI42966618530、64对象链接/分支/加载器与新路径字段检查通过，槽1已准备读回，正在部署临时启动。
保留Hall/120Hz，先普通Snapshot/HaltResume，再live-identity轮询接管；槽1归GPU206，回收前其他任务不操作。
状态log/host/gpu-v206/continuation.json，目标active，不额外重启Android。

GPU206提交003b445：nabu-dpu-live-identity=1在M=0旁路下预置全部配置与TLBI，再启用永久GOP恒等映射，不写XIN暂停。
Display/Mapper ARM64、13组隔离及19组原始翻帧/生命周期回归通过；已推送等待完整CI，未准备新槽/部署。
设备Android/USB归GPU206，Data183，GPU205日志已回收清槽。保留Hall/120Hz，不额外重启Android，目标active。
状态log/host/gpu-v206/continuation.json；GPU206去除halt-audit=1，先普通Snapshot/HaltResume再轮询接管和视觉验收。

GPU205完整日志已回收：3,303,236字节及完整64MiB槽保存清空读回，引导分区未变，Data183，设备Android/USB归GPU。
只读检查2.04s、SCTLR0xe0、programmed0/frozen0且用户黑屏，证明实际翻译启用不是必要条件；未发起真正接管。
GPU206准备旁路下预置、恒等映射使能切换，避免长时间XIN暂停；未准备新槽/部署。保留Hall/120Hz，不额外重启Android。
目标active，当前已完成状态log/host/gpu-v205/continuation.json。

GPU205只读对照也黑屏：halt-audit2042027us，SCTLR0xe0未启用翻译，最终status0/programmed0/frozen0；用户确认背光亮但纯黑。
新IRQ/双vsync各13，无新增underrun；AFC及独立读取超时。尚未发起任何ActivateGop/ResumeIrq/FlipGop。
已请求恢复Android，GPU205槽1尚未回收，其他任务不覆盖；目标active。接续先回收，再缩短XIN停取数窗口。
状态log/host/gpu-v205/continuation.json；以下部署前记录为历史。

GPU205完整内核CI42963052903、64对象链接/分支/加载器及只读诊断字段检查通过，槽1已准备读回，正在部署临时启动。
本轮先Snapshot与带halt-audit=1的DpuHaltResume只读对照，确认画面后才考虑真正接管；槽1归GPU205未回收。
保持Hall/120Hz、不额外重启Android；目标active，状态log/host/gpu-v205/continuation.json，其他任务不操作设备/槽。

GPU205提交e44559a：DpuHaltResume增加nabu-dpu-halt-audit=1只读对照；临时Mapper不激活，恢复后释放，结果明确未改SMMU。
Display/Mapper ARM64与11组隔离/生命周期回归通过，已推送等待完整CI；尚未准备GPU205日志槽/部署。
Android/USB归GPU205，Data182，GPU204已回收清槽；保留Hall/120Hz，不额外重启Android。
目标active，状态log/host/gpu-v205/continuation.json；先只读对照和画面验收，之后才考虑真正接管。

GPU204黑屏回收完成：3,397,305字节与完整64MiB槽已保存清空读回，引导分区未变，Data182；设备Android/USB归GPU。
接管774169us中sources214181、末尾routes402621、TLBI1979、enable1007；延迟在首次SMMU写入前的只读检查已出现。
两次mapper快照通过，但本轮持久化末尾未含最终result/frozen0；不得声称本轮最终完成。GPU205尚未准备/部署。
目标active；下一步分离停取数时只读SMMU检查与真正翻译启用。状态log/host/gpu-v204/continuation.json。

GPU204桌面/触摸/GPU ready及Snapshot/HaltResume通过；轮询接管后用户确认背光亮但纯黑，配对和独立读取超时。
已请求恢复Android回收分段时间；槽1尚未回收，仍归GPU204，其他任务不得覆盖或操作。未恢复IRQ/翻帧。
目标active，状态log/host/gpu-v204/continuation.json；以下部署前状态为历史。

GPU204完整内核CI42960087275、64对象链接/分支/加载器与时间戳字段检查通过，槽1已准备读回，正在部署临时启动。
本轮槽1归GPU204；回收前其他任务不操作设备/日志槽，复用GPU201启动包，保留Hall/120Hz，不额外重启Android。
动态状态log/host/gpu-v204/continuation.json，目标active；以下准备阶段为历史。

GPU204提交34107c6：只记录11个无输出的接管阶段时间，恢复后输出/存字典；ARM64/实际Mapper及8组隔离回归通过。
完整内核CI进行中，GPU204尚未准备日志槽/部署。设备Android/USB归GPU，Data181，GPU203日志已回收清槽读回。
保持Hall/120Hz，不额外重启Android；目标active，动态状态log/host/gpu-v204/continuation.json。

GPU203仍背光亮但纯黑；完整日志测得quiesce14us/program777392us/resume6034us/总暂停789326us，最终status0/frozen0。
3,362,247字节与完整64MiB槽已回收清空读回，引导分区未变，Data181，设备Android/USB仍归GPU。
普通成功日志不是黑屏必要条件；继续细分无输出的接管耗时，GPU204尚未准备/部署。保持Hall/120Hz，不额外重启Android。
目标active，状态log/host/gpu-v203/continuation.json；以下部署/运行状态为历史。

GPU203完整内核CI42957733910、64对象链接/分支/加载器通过，槽1已准备读回，正在部署临时启动。
复用GPU201助手/启动包，保留Hall/120Hz；本轮槽1归GPU203，回收前其他任务不操作设备/槽。
状态log/host/gpu-v203/continuation.json，目标active，不额外重启Android；以下准备阶段为历史。

GPU203提交73696bb：移出停取数成功路径的普通IOLog，新增quiesce/program/resume/总暂停时间；原GPU202寄存器流程不变。
Display/Mapper ARM64及8组隔离回归通过，完整内核CI42957733910进行中；尚未准备GPU203日志槽或部署。
Android/USB仍归GPU，GPU202日志已回收清空读回，Data180；保持Hall/120Hz，不额外重启Android。
目标active；状态log/host/gpu-v203/continuation.json。Arm规范已确认S2CR/SCTLR SHCFG不是M=1时最终共享属性的依据。

GPU202轮询接管status0/frozen0、8000个GOP样本一致且非黑，用户仍确认背光亮但纯黑；未恢复IRQ/翻帧。
4,071,234字节有效前缀和完整64MiB槽已回收清空读回，引导分区未变，Data180；设备Android/USB归GPU。
完整目标active，继续核实SHCFG/硬件取数路径；GPU203尚未准备或部署。保留Hall/120Hz，不额外重启Android。
状态log/host/gpu-v202/continuation.json；以下部署/运行状态为历史。

GPU202提交a597522：对齐原机V500 upstream页表遍历/ACTLR，WB表池按实际脏表页发布PoC，新增GOP首尾样本。
GPU202完整内核CI42953709914、64对象链接/加载器通过；槽1已准备读回，正在部署临时启动。
复用已验GPU201助手/启动包，保留Hall/120Hz；设备Android/USB归GPU202，不额外重启Android。
完整目标active；状态log/host/gpu-v202/continuation.json；原机配置差异尚未实机证明是黑屏根因。

GPU201轮询接管走到status0/frozen0，显示IRQ一直屏蔽，用户仍确认背光亮而纯黑；未恢复IRQ/翻帧。
3,265,673字节与完整64MiB槽已回收清空读回，引导分区未变，Data179，设备Android/USB归GPU。
IRQ恢复不是黑屏必要条件；下一步对照原机translation/实际扫描内容，完整目标active。
状态log/host/gpu-v201/continuation.json；以下准备/运行记录为历史。

GPU201提交3aca035：新增接管时保持IRQ屏蔽的轮询控制，随后单独ResumeIrq；两项通过才准入翻帧。
GPU201完整内核/助手CI、64对象链接和加载器/APFS检查通过，槽1已准备读回，正在部署临时启动。
GPU200完整槽已回收清空读回，Data178、引导分区未变；设备Android/USB归GPU201，保留Hall/120Hz。
完整目标active；状态log/host/gpu-v201/continuation.json，不额外重启Android。

GPU200已临时启动，桌面/触摸和Snapshot/HaltResume通过；用户确认页表接管后持续黑屏。
GPU200完整64MiB槽与3,261,109字节有效前缀已回收清空读回，引导分区未变；设备Android/USB归GPU。
CB2/context/routes/4000页读回一致，最后为resumed-counters-read的checkpoint返回；下一项拆开接管与IRQ。
状态log/host/gpu-v200/continuation.json；以下启动准备记录为历史。

GPU200提交e015fdf：原机GOP NC属性对照、恢复后提前fault/mapper读回与独立原始表面/GOP往返。
Display ARM64全文/12生命周期/19真实函数往返回归通过；完整内核CI42940474475和helper CI42940473297均通过。
GPU199黑屏完整64MiB和5,663,714字节已回收清槽读回，引导分区未变，Data177；GPU200槽1已准备读回，设备与日志槽归本轮。
设备Android/USB归GPU200；保留Hall/120Hz，不额外重启Android。尚未声称页表接管或黑屏修复实机通过。
用户已恢复四阶段目标；GPU200内核下载完成，继续64对象链接、加载器检查和已授权实机验证。
状态log/host/gpu-v200/continuation.json，报告analysis/nabu-gpu-v200-roundtrip.md；目标active。

GPU198完整日志证明CB2 active、XIN恢复、IRQ重启均已返回，最后为GOP identity enabled；画面仍黑屏/卡住。
3469096字节与完整64MiB槽已回收清空读回，引导分区未变。此前Snapshot/HaltResume通过，短暂停14us/恢复11us。
设备Android/USB继续归GPU；下一步只补接管后验证/结果记录，保留GPU198寄存器流程；不再按CB2关闭失败推断。
保留Hall/120Hz，不额外重启Android。状态log/host/gpu-v198/continuation.json；四阶段目标active。

GPU197页表接管后黑屏/卡住，完整日志证明XIN暂停成功，进入CB2编程，最后检查点cb2-disable-enter。
3750838字节与完整64MiB槽已回收清空读回，引导分区未变；在线syslog比持久化日志少，不能再归因为VBIF暂停。
设备Android/USB继续归GPU；下一步核对CB2停用与暂停区间同步日志，未准备新槽。保留Hall/120Hz，不额外重启Android。
状态log/host/gpu-v197/continuation.json；完整四阶段目标active。

GPU197完整CI42846033361、helper CI42846033418、64对象链接和加载器检查通过，槽1已准备读回，正在部署临时启动。
先桌面后Snapshot/HaltResume/ActivateGop，保留原GOP地址；Hall/120Hz保持，不额外重启Android。
槽1归GPU197，其他任务不操作设备/槽；动态状态log/host/gpu-v197/continuation.json。

GPU196三次独立halt/resume及桌面触摸通过，4334099字节和完整64MiB槽已回收清空读回，引导分区未变。
GPU197提交172e318：同启动先Snapshot/HaltResume，再独立CB2接管，保留GOP identity，不翻帧；本地mapper/并发/ARM64通过。
云端内核与helper编译中，设备Android/USB归GPU197；未准备新槽/部署。保留Hall/120Hz，不额外重启Android。
动态状态log/host/gpu-v197/continuation.json；完整四阶段目标active。

GPU196独立DPU测试通过：root快照+三次真实XIN0/4 halt/resume，ACK解除/时钟/GOP地址/双计数/IRQ恢复均通过。
用户确认三次后桌面/触摸保持正常；页表接管和翻帧仍待验，完整四阶段目标active。
设备目前iPadOS，槽1归GPU196且未回收；其他任务不操作设备/槽。状态log/host/gpu-v196/continuation.json。

GPU196 helper CI42843133723通过，root专用job与Hall库APFS读回通过；同GPU195内核保持不变。
槽1已准备读回，开始部署并临时启动；不额外重启Android，保留Hall/120Hz。
槽1归GPU196，其他任务不操作设备/日志槽；状态log/host/gpu-v196/continuation.json。

GPU195桌面/触摸/GPU就绪通过；DPU请求因原助手UID501返回e00002c1，未进入诊断MMIO。
3854535字节日志及完整64MiB槽已回收清空读回，引导分区未变，设备Android/USB归GPU196。
GPU196复用GPU195内核，仅增加--dpu-only root专用助手；提交911d1ae，helper CI42841523643进行中。
尚未准备新槽/部署，不额外重启Android，保留Hall/120Hz；状态log/host/gpu-v196/continuation.json。

GPU195完整CI与64对象链接/加载器检查通过，槽1已准备读回，正在部署并临时启动。
本轮nabu-dpu=0、nabu-dpu-diag=1，桌面后单独请求DPU诊断；保留Hall/120Hz。
槽1归GPU195，其他任务不覆盖/操作设备；不额外重启Android。状态log/host/gpu-v195/continuation.json。

GPU195提交a2b18bc：桌面后独立Snapshot/HaltResume，GOP扫描地址保持不变；本地11组并发回归和ARM64通过。
完整内核CI42837281278、helper CI42837281139进行中，尚未部署/准备新槽。
设备Android/USB归GPU195；GPU194完整槽已回收清空读回，保留Hall/120Hz，不额外重启Android。
状态log/host/gpu-v195/continuation.json，完整四阶段目标active。

GPU194同GPU192内核仅DPU关闭对照通过：桌面/触摸正常，新MetalPresent 64帧双路各4194304像素0错，
直接共享3次、copy/shadow0、清除后全部释放。完整64MiB槽已回收清空读回、引导分区未变。
设备Android/USB继续归GPU；GPU195准备桌面后独立暂停/恢复诊断，不额外重启Android，保留Hall/120Hz。
完整四阶段目标active，第一阶段通过，其余待验；状态log/host/gpu-v194/continuation.json。

GPU194同GPU192内核仅DPU关闭对照已部署读回并临时启动，USB和GPU就绪通过，在线日志持续。
桌面/触摸和新MetalPresent 64帧双路像素/共享页/释放均通过；槽1属于GPU194且未回收，其他任务不操作设备或槽。
完整四阶段目标保持active；动态状态log/host/gpu-v194/continuation.json。

用户已设定完整GPU目标并授权推进四阶段。GPU194开始同GPU192内核仅关闭DPU的对照；
GPU193 ACK顺序候选保留未启动。设备Android/USB归GPU194，GPU192日志已回收清空读回。
保持Hall/120Hz，不额外重启Android。动态状态log/host/gpu-v194/continuation.json。

用户最新要求先对比正常/黑屏内核。已完成Hall03/GPU186与GPU192实际Mach-O、部署输入和日志对照，
报告analysis/nabu-good-vs-black-kernel-20261110.md：新增DPU强制呈现及VBIF暂停是回归路径，
具体store/DSB/后续日志边界仍未取得故障PC。GPU193完整CI42829663050与镜像检查通过，但未部署。
设备保持Android/USB，GPU192槽已清空；下一项可用同一GPU192内核仅关DPU作对照，配置已离线准备。
不额外重启Android，保留Hall/120Hz。动态状态log/host/gpu-v193/continuation.json。

GPU193提交f9f49ea，本地扫描协议回归及ARM64通过，完整CI42829663050进行中。
按原机VBIF写后直接读取真实ACK，再执行完成屏障；ACK前不调用同步诊断。
GPU192日志已回收清槽，设备Android/USB归GPU193；本轮尚未准备日志槽或部署。
动态状态log/host/gpu-v193/continuation.json，保留Hall/120Hz，不额外重启Android。

GPU192仍黑屏，完整64MiB槽及798598字节日志、691865字节syslog已保全，槽清空读回，APFS171。
显示IRQ屏蔽成功后仍停于VBIF0x200写0x11入口；引导分区未变，设备Android/USB归GPU193。
GPU193按原机relaxed写后读ACK，完整屏障放在ACK之后，避免诊断在ACK前同步写盘；
本地回归/ARM64验证中，尚未准备槽或部署。保留Hall/120Hz，不额外重启Android。
动态状态log/host/gpu-v193/continuation.json；以下GPU192未回收状态为历史。

GPU192已部署读回并临时启动，原生USB及在线syslog已连接；正在观察首帧与等待用户画面反馈。
槽1属于GPU192，尚未回收；其他任务不覆盖槽或启动候选。保留Hall/120Hz。
动态状态log/host/gpu-v192/continuation.json。

GPU192完整CI42826799996、64对象链接与加载器检查已通过，开始准备日志槽并部署临时启动。
槽1本轮归GPU192；设备仍由GPU使用，保留Hall/120Hz，不额外重启Android。
动态状态log/host/gpu-v192/continuation.json；其他任务不覆盖槽或启动候选。

GPU192已提交303b65d：在XIN暂停/CB2切换前屏蔽显示IRQ并排空回调，恢复后重采样。
本地IRQ/显示生命周期回归及ARM64通过；完整CI42826799996进行中，尚未部署或准备槽。
设备Android/USB仍归GPU192；保留Hall/120Hz，不额外重启Android。
动态状态log/host/gpu-v192/continuation.json。

GPU191仍黑屏，完整64MiB槽及808996字节日志已回收清空读回，APFS170，引导分区未变。
逐条检查点确认VIG时钟读写与VBIF读取均返回，最后为VBIF0x200写0x11入口，未进入CB2。
设备Android/USB，继续归GPU；下一轮尚未准备槽，保留Hall/120Hz，不额外重启Android。
动态状态log/host/gpu-v191/continuation.json；以下GPU191未回收记录为历史。

GPU191完整CI、64对象链接及加载器检查通过，已部署读回并临时引导成功，等待原生USB。
槽1属于GPU191，尚未回收；设备仍归GPU。保留Hall/120Hz，不额外重启Android。
动态状态log/host/gpu-v191/continuation.json；其他任务不覆盖槽或启动候选。

GPU190完整64MiB槽及818053字节日志已回收清空读回，APFS169，引导分区未变。
实机检查点确认表面映射/producer/页表/源检查成功，停于xin-quiesce入口，未进入CB2。
GPU191修正先开VIG时钟再访问VBIF，并逐步记录该段MMIO；本地回归/ARM64通过，
完整CI42823449308进行中。设备Android/USB且归GPU191；尚未准备新槽，不额外重启Android。
动态状态log/host/gpu-v191/continuation.json；以下GPU190未回收状态为历史。

GPU190已临时启动，用户确认仍在进入iPadOS时黑屏，在线诊断超时。
已请求恢复Android；槽1含本轮检查点日志，尚未回收。设备仍归GPU，
其他任务不覆盖槽或启动候选。动态状态log/host/gpu-v190/continuation.json。

GPU188/189均在XNU之后进入iPadOS图形界面时黑屏。两轮完整64MiB槽已备份清空读回，
GPU189有效日志799545字节，APFS168，Android引导分区未变；设备Android/USB，归GPU190。
GPU190完整CI、64对象链接和加载器检查通过，槽1已准备读回，开始部署/临时启动。
保留Hall和120Hz，不额外重启Android；槽1归GPU190，本轮回收前其他任务不占用。
动态状态log/host/gpu-v190/continuation.json；以下GPU188/189未回收记录为历史。

软件后续核查确认：sensors07原始App实际等待不存在的SPU6轴HID0xff0c/5（9条日志）。
已生成的新mode4包目前只完成原始三轴/HID候选，融合AP/Legacy路径选择尚未适配，
系统方向的capability bit6选择也待确认；不能把新包称为融合/旋转已修复。设备仍归GPU。
证据log/host/sensors-fastrpc-20261109/software-layer-20261110/fusion-rotation-status.json。

GPU188已部署并读回成功，正在从Android直接切bootloader临时启动；
完整CI、64对象链接及加载器检查通过，修复16KiB VM页号换算，保留Hall和120Hz。
槽1属于GPU188，尚未回收；其他任务继续本地工作，不占用设备或日志槽。
动态状态log/host/gpu-v188/continuation.json；不额外重启Android。

用户要求继续软件层适配：已修正原版HID Remove的void ABI、旧client跨代数据/控制，
以及ALS ConformsTo的32位返回类型。原生消费者App新增独立HID观测和重新采样。
专项CI42804854787、真实CF回归、内核9170项回归、ARM64/加载器和454项APFS读回通过。
mode4候选artifacts/nabu-sensors-native-hall-gpu186-20261110-r3-software及
artifacts/nabu-bootstrap-hall-gpu186-native-software/bootstrap.apfs已保存，原生API尚未实测。
设备继续归GPU，传感器不操作设备/日志槽。后续上机先使用交回时最新合格GPU基底。
状态log/host/sensors-fastrpc-20261109/software-layer-20261110/continuation.json；
分析analysis/nabu-sensors-software-20261110.md。

GPU187黑屏原因已定位：显示页表缓存检查将16KiB VM页误按4KiB计算pmap页号，
查询到错误地址后返回IO属性7，首帧被拒绝；GPU就绪、120Hz上报和producer注册均通过，
尚未进行DPU扫描地址切换。4,767,693字节及完整64MiB槽1已回收清空读回，APFS166，
Android引导分区未变。继续GPU188修复页号换算，设备Android/USB且仍归GPU；
不额外重启Android，其他任务暂不占用设备或槽。见log/host/gpu-v188/continuation.json。

sensors08本地分析完成：加速度206、陀螺仪206、磁场393、前置ALS1个真实样本，
全单调，五份三轴配置与原机字节相等。空SUID后84–86ms出现真实三轴，更新订阅
修复实机通过。4,533,731字节及完整64MiB由GPU187回收清槽，APFS165、引导分区未变。
时钟回放和mtime修复本地检查通过，mode4及匹配新启动包已保存，原生API仍未实测。
设备继续归GPU187；传感器不操作设备/日志槽。详见analysis/nabu-sensors05-08-registry-20261110.md
及log/host/sensors-fastrpc-20261109/continuation.json。下文未回收状态为历史。

GPU187已接手设备：用户明确授权开始测试，sensors08完整64MiB槽及4533731字节运行日志
已由GPU回收并清空读回，Android引导分区未变。当前Android/USB，准备GPU187临时启动。
完整CI、64对象链接、分支和加载器检查均通过；保留Hall03及120Hz配置。
GPU187日志回收前其他任务不占用设备或日志槽，不额外重启Android。
动态状态见log/host/gpu-v187/continuation.json；以下为历史交接记录。

2026-11-10用户在“34”明确选择“通知并交给GPU187”，现设备归GPU187。
sensors08在交接消息到达前已经部署并临时启动成功，USB已看到；无运行中设备命令。
槽1已承载本轮运行日志，不是只有预备清单，尚未回收或清空。GPU开始前须在Android
回收log/device/nabu-boot-20261110-sensors08完整日志并清槽读回，不能直接覆盖槽1。
传感器6停止设备/日志槽操作，仅继续本地工作；GPU187回收前不再启动传感器候选。
明确交接凭据：log/host/sensors-fastrpc-20261109/sensors08/handover-to-gpu187.json。
以下设备归属为历史。

sensors07已回收：6,422,876字节有效日志及完整64MiB槽1已保存、清空并读回，
Android引导分区未变、APFS164。registry正常，前置ALS11个真实样本，三轴仍为空SUID。
设备Android/USB，继续由传感器6测试；正在构建sensors08，单次订阅SUID更新并保留3秒
发现窗口，同时读回实际APFS配置。保持Hall03和GPU185/186 120Hz，不额外重启Android。
状态log/host/sensors-fastrpc-20261109/continuation.json。以下传感器状态为历史。

sensors05已验证原生APFS registry：139个原机文件补齐成功，175次写入、94次rename成功，
但15秒期限在仍生成配置时中止，SSC尚未采样。4,436,731字节有效记录和完整64MiB槽1
已备份清空读回，APFS162、引导分区未变。传感器6继续sensors06，将registry时限改45秒，
保持整体60秒上限、Hall03对象/两库、GPU185/186和120Hz；设备继续归传感器6。
状态log/host/sensors-fastrpc-20261109/sensors06/continuation.json，不额外重启Android。

用户继续要求直到iPadOS正确读取并使用传感器；传感器6开始sensors05。
原生APFS registry及FastRPC文件写入实现、真实磁盘/协议回归、ARM64/分支/加载器检查通过，
仍保留GPU185全部对象、GPU186 120Hz配置和GPU180系统启动包；设备归传感器6，
准备新槽后临时启动，不额外重启Android。状态log/host/sensors-fastrpc-20261109/sensors05/continuation.json。

2026-11-10 hall03已通过并释放设备：用户确认霍尔正常、正确锁屏、桌面/触摸正常。
保留GPU185对象、GPU186 120Hz配置、GPU180系统启动包，加入GPIO9 Hall及锁屏策略；
日志记录3次开合、3次阻止SmartCover自动解锁、9次背光请求均校验通过，并有后续
原生锁屏滑动退出记录。3,293,338字节有效日志、完整64MiB槽1、10,785,901字节syslog
已备份；槽1清空读回通过，Android引导分区未变，APFS161，设备Android/USB。
合格内核artifacts/nabu-hall-gpu186-20261110/kernel/kernel.native-apfs.macho；启动包
artifacts/nabu-bootstrap-hall-gpu186-20261110/bootstrap.apfs。后续基线整合应保留Hall对象、
输入/锁屏两库和nabu-hall=1。状态log/host/hall-lockscreen-20261110/continuation.json。
未准备下一槽；不额外重启Android。本轮不增加GPU/120Hz、深睡或长时间合盖验收结论。

sensors04真机复测完成：已沿用“34”GPU185全部对象、GPU186 120Hz配置和GPU180系统启动包。
用户确认桌面/触摸正常，GPU ready、原生显示查询120Hz；SMMU第三订阅修复实机通过，
SLPI DMA active1/phase8/status0，FastRPC注册和1,377次反向请求成功。当前registry写入
temp.json被只读服务拒绝503次，版本写入拒绝10次，registry超时、SSC未开始、样本0。
3,850,332字节记录与完整64MiB槽1已备份清空并读回，APFS160、Android引导分区未变。
设备Android/USB，下一轮未准备日志槽；后续必须继续使用“34”的合格新内核/GPU启动包，
不得再部署旧display01传感器候选，不额外重启Android。状态见
log/host/sensors-fastrpc-20261109/sensors04/continuation.json。以下sensors04运行状态为历史。

sensors03已回收3,272,532字节有效日志和完整64MiB槽1，清槽读回通过，Android引导分区未变。
实测SLPI启动成功但DMA phase3/status10注册失败；共享全局SMMU IRQ仅2槽，
WLAN/ADSP占满后第三路SLPI主机回归复现。现已扩为3槽且三路共存/退出/故障测试通过。
用户要求下次使用“34”新内核，sensors04已改用GPU185全部GPU对象、GPU186 120Hz配置
和GPU180系统启动包；新增SLPI与重编译的中断控制器，所有GPU对象保留，加载器检查通过。
sensors04已临时启动，用户确认桌面/触摸正常；设备仍由传感器6占用，槽1未回收；动态状态log/host/sensors-fastrpc-20261109/sensors04/continuation.json。

2026-11-10用户在“传感器6”明确要求开始真机测试，本对话接续sensors03。
GPU186回收凭据已确认：5,260,347字节前缀和完整64MiB槽1已保全，清槽读回通过，
Android引导分区未变；GPU continuation尚未同步不影响已完成的回收凭据。
sensors03已部署并临时启动mode3 r6和FastRPC r2；用户确认iPadOS桌面/触摸正常。
传感器诊断App已安装，USB日志采集中；槽1尚未回收，设备归传感器6。
本轮日志回收前不准备其他测试槽或启动其他候选；不额外重启Android。
动态状态见log/host/sensors-fastrpc-20261109/continuation.json。以下GPU186运行状态为历史。

GPU186的120Hz设置已实机确认：原生diagnostics_relay按EntryClass=IOMobileFramebuffer
读取实时IORegistry，1600x2560，SyncRate/PreciseSyncRate=7864320(120Hz)，
IOMFBDisplayRefresh间隔35791394(32.32，约8.33ms)。用户桌面/触摸正常，提升不明显或仍撕裂。
设备当前保持iPadOS 120Hz，槽1尚未回收；下轮必须先收集186日志，不覆盖此槽。
ADT无独立刷新率字段，120参数通过DarwinBoot CommandLine传入；源码后续默认也120。
未声称硬件vblank、无撕裂或120个不同画面/秒已实现。状态见log/host/gpu-v186/continuation.json。

用户已明确先将内核设置为120Hz。GPU186使用fb_hz=120和fb_ca_hz=120，
复用185内核和180启动包；源码默认值也改为120供后续编译。配置与补丁应用检查通过，
准备部署临时启动。此项为软件节拍与上报刷新率，不等同硬件vblank、无撕裂或整链路120fps。
设备仍归GPU，Android/USB，185日志已回收清槽、APFS157；不额外重启Android。
见log/host/gpu-v186/continuation.json。

GPU185实测面板已在约120Hz运行：双INTF周期8.330714ms，250.334ms采样各29次递增，
无跳帧计数；驱动仍是60Hz软件节拍。显示SMR3=84200800/S2CR=2，CB2 SCTLR=e0，
当前旁路直读GOP；DPU原生IOSurface扫描、硬件换帧/退休及120Hz回调尚未实现，仍有撕裂。
3,277,045字节前缀和完整64MiB槽已保全清空，APFS157、Android引导分区未变。
设备Android、USB连接，仍由GPU使用；不额外重启Android。下一步无需修改面板模式，
继续显示端共享页扫描和同步呈现。见log/host/gpu-v185/continuation.json。

GPU184共享页实测通过：64帧双路各4,194,304像素0错，3个直接导入、复制和shadow均0，
清除后全部释放；11个系统客户端成功，含3个高地址新窗口。设置/搜索正常但仍撕裂。
4,627,729字节及完整64MiB槽已回收清空，APFS156、Android引导分区未变。
继续GPU185只读实测硬件扫描频率与显示SMMU路由，保留184共享页；设备归GPU，
不额外重启Android。状态见log/host/gpu-v185/continuation.json。

GPU183日志已回收清槽：8,606,535字节与完整64MiB槽保全，APFS155、Android引导分区未变。
新App在第9个连接因8槽耗尽返回e00002db，尚未测试共享页一致性；缓存共享已启用，
用户确认桌面更流畅但撕裂。GPU184保留原8窗口并扩展32位GPU软件地址范围，新增16槽，
共享页及只读DPU诊断本地编译/地址/页表/分支检查通过，准备临时启动。设备仍归GPU，
不额外重启Android。动态状态见log/host/gpu-v184/continuation.json。

# 项目工作规则

用户最新明确目标：当前60Hz先流畅，最终跑满面板120Hz；尽量沿用原版Apple路径，
IOSurface直接共享物理页，不以副本复制作为目标方案。GPU182复制优化候选停止上机，
已请求取消专项CI42765051759。主线转普通缓存IOSurface直接导入、原生生命周期/同步、
合成和DPU呈现；120Hz面板模式修复后置。GPU181日志已保全清槽，设备Android、APFS154，
仍归本GPU对话；不额外重启Android。见log/host/gpu-zero-copy/continuation.json。

GPU181已回收清槽：App标准工厂和64帧256×256双路各4,194,304像素0错，清除释放通过；
7个进程占用0..6槽且无连接拒绝。用户确认实际输出仍约1–3帧/秒，性能未通过。
4,623,704字节前缀和完整64MiB槽已保全，APFS154、Android引导分区未变，设备Android。
继续GPU182复制同步热点对照及限量耗时诊断，尚未准备新槽或部署。设备仍由GPU使用；
不额外重启Android。见log/host/gpu-v182/continuation.json。以下181运行中记录为历史。

GPU180日志已回收：4,165,437字节有效前缀和完整64MiB槽1，清槽读回通过，APFS153，
Android引导分区未变。IOServiceOpen的e00002db已证实为四个连接槽耗尽；继续GPU181，
保留原窗口并新增4个独立窗口，本地ARM64编译、地址/复用测试、内核分支及引导布局通过。
GPU181已部署并临时启动，USB及GPU就绪通过，SpringBoard/chronod前端初始化未再
记录旧设备拒绝，但有一次fence超时；用户确认桌面仍明显卡顿，正在测试普通App。槽1未回收，
设备仍由本GPU对话使用；不额外重启Android。见log/host/gpu-v181/continuation.json。

第180轮已续发临时引导，用户确认进入桌面、触摸正常；GPU就绪检查通过。普通App
在标准工厂创建设备时返回Vulkan(-3)、0帧，SpringBoard和chronod也出现相同拒绝；
不能称应用或全系统加速通过。实时日志已保存，已请求恢复Android回收槽1，回收前
其他任务继续本地工作；状态见log/host/gpu-v180/continuation.json。

第180轮专项CI42757503932完整成功，源映射生命周期/资源alias修复及原生测试通过，
新驱动下载审查、启动包APFS和12项读回通过，已准备槽1并开始部署临时启动。
复用display01内核，不额外重启Android；设备仍由本对话GPU使用。日志回收前
其他任务不得占用设备或日志槽。状态见log/host/gpu-v180/continuation.json。

第180轮复制源自有共享映射已完成，源码42adccb在真实macOS通过8组Mach和生产
CopiedBuffers同步用例，涵盖原VA保护/撤销/复用与释放。初次CI在Rust编译前因
新补丁清单未登记停止，20faac2已修复，专项CI42757503932正在运行。设备为Android、
APFS152，未准备第180轮日志槽；实机桌面未验收。见log/host/gpu-v180/continuation.json。

第179轮日志已回收清槽：47,326,534字节有效前缀和完整64MiB槽，APFS152，
Android引导分区未变、设备在Android。31次桌面SIGSEGV同址：系统memmove从
CopiedBuffers::copy_in的pages首个8字节读取失败，具体源VA失效时点未证实。
资源接口CI42738127415及下载审查通过；本对话继续第180轮源映射生命周期修复，
未准备新日志槽。见log/host/gpu-v179/continuation.json及gpu-v180/continuation.json。

第179轮定点诊断已临时启动并再次复现桌面signal11退出，syslog已保存31,071,999字节；
已请求用户恢复Android，当前179日志槽1尚未回收，不能准备其他槽或启动其他候选。
返回后先取NABU_METAL_FAULT的PC/LR和镜像基址，再继续修复。资源桥接CI42738127415
仍在运行，系统工厂及完整8796 CI均成功；本次179尚未装入新的资源alias实现。
动态状态见log/host/gpu-v179/continuation.json；以下部署前状态为历史。

第179轮先执行定点诊断：工厂CI42738127355和真实SIGSEGV主机测试通过，
复用已审查GPU178前端，资源alias新实现仍在CI42738127415编译，本次179不含它。
诊断启动包APFS和12项读回通过，准备复现桌面异常并取回PC/LR；设备仍由GPU使用，
复用display01内核，不额外重启Android。见log/host/gpu-v179/continuation.json。

第178轮GPU系统实测未通过：用户黑屏，媒体9次makeAliasable缺失abort；桌面5次
SIGSEGV，QuartzCore fence超时与崩溃因果未定。8,972,301字节有效前缀、完整64MiB槽1
和21,830,199字节syslog已保全清槽，APFS151、Android引导分区未变，设备恢复Android。
本对话继续179：真实资源alias桥接及backboardd故障地址诊断，尚未准备新日志槽。
动态状态见log/host/gpu-v178/continuation.json和log/host/gpu-v179/continuation.json；
其他对话继续本地工作，未交出设备。以下178部署记录为历史。

2026-11-10用户通知第178轮云端编译完成，本对话接续已授权的系统GPU真机复测。
专项CI42653980143成功，正在取回uchar3和pipelineLibrary修复产物并合成启动包。
设备为Android、USB在线、无线关闭；继续复用display01内核，不额外重启Android。
第178轮日志回收前其他对话保持本地工作，不能占用设备或日志槽。动态状态见
log/host/gpu-v178/continuation.json。以下GPU177状态为历史记录。

第177轮系统GPU已实测：原版backboardd和mediaserverd实际加载NativeBridgeMetalDevice；
原始常量type51=uchar3被前端拒绝，媒体进程缺少pipelineLibrary函数重载，桌面未完成。
3,356,432字节连续前缀和完整64MiB槽1备份清空，APFS150、Android引导分区未变；
设备已恢复Android，本对话继续第178轮两项明确兼容修复，尚未准备下一日志槽。
见log/host/gpu-v177/continuation.json及log/host/gpu-v178/continuation.json。

2026-11-10用户在“32”明确表示设备已释放并授权开始，第177轮系统GPU实测由本对话
接手。Hall02完整日志已备份清空，设备为Android、USB连接、无线关闭。使用已合格
display01内核和v177-r2系统GPU启动包，CI42650459047通过；不额外重启Android。
其他对话继续本地工作，本轮日志回收前不占用设备或日志槽。状态见
log/host/gpu-v177/continuation.json；以下设备归属为历史记录。

“霍尔开关3”开盖停在锁屏候选已在本地合格：20F66原版控制流和32位来源ABI已核对，
仅SmartCover来源3禁止自动解锁，保留原生唤醒及其他来源；提交19074c2，58项主机
用例和专项CI42654906255编译/签名均通过。启动包为
artifacts/nabu-bootstrap-hall-lockscreen-20261110/bootstrap.apfs（68,034,560字节），
APFS及69,104字节新setup库、原Hall输入库读回通过，复用hall02实测r3内核。
状态见log/host/hall-lockscreen-20261110/continuation.json。未准备日志槽、未部署或
启动新候选；设备继续由其他对话使用，须用户交回后再验收锁屏画面及正常滑动解锁。

2026-11-10“霍尔开关3”hall02已结束并释放设备：r3进入桌面，三次合盖熄屏/开盖
唤醒、锁屏后合盖保持15秒、按键与触摸均正常。4,125,010字节有效日志前缀、完整
64MiB槽1及12,596,768字节syslog已备份，槽已清空并读回，Android引导分区未变。
设备为Android、USB连接、无线关闭；用户将交给其他对话，本对话不再启动候选。
6次合盖/开盖及17次背光请求验证通过；原生SmartCover开盖会自动解锁，用户明确
要求下一步改为“开盖只唤醒并停在锁屏”，此项尚未实现/实测。状态见
log/host/hall-20261109/hall02/continuation.json；以下设备归属为历史记录。

“32”按用户要求优先接入系统GPU，第177轮已实现普通进程Metal工厂、进程缓存及
backboardd/SpringBoard就绪后exec原程序，启动参数nabu-gpu-delay=0；普通名App只链接
系统框架。最终专项CI42650459047及APFS/12项读回通过，已生成v177-r2系统接入包。
平板仍归“传感器5”，已向用户询问交接，GPU未准备日志槽、未部署、未启动。
动态状态见log/host/gpu-v177/continuation.json；不能把接入候选称为桌面加速实测通过。

当前用户已在“霍尔开关3”明确要求开始真机测试，由该对话执行hall02：使用已合格
GPIO9地址修正r3内核。sensors02完整日志已备份清空、设备已在Android；重新建立槽1
回执后部署并临时启动。hall02日志回收前其他候选不得占用此槽或启动；传感器/GPU
可继续本地工作。状态见log/host/hall-20261109/hall02/continuation.json，
旧Hall02预备槽回执已被GPU175释放，不能复用；仍不额外重启Android。

“传感器5”已接续并回收sensors02：3,025,967字节有效前缀和完整64MiB槽1已备份、
清空并读回；APFS147→148，boot partitions unchanged，设备为Android、无线关闭。
SLPI/GLINK及正常退出通过，7个SSC查询均成功应答，但七类SUID发现全部Timeout，
streams=0，iPadOS真实样本仍为0；不能称传感器修复通过。Android当次对照四路采样正常。
下一步核对并实现FastRPC sensor_pd及registry文件服务，不能把缺失实现直接当成已证明
的唯一原因。尚未准备或启动下一轮，状态见log/host/sensors-live-20261109/continuation.json。
以下sensors02等待回收状态为历史记录；仍不额外重启Android。

用户已在“传感器4”明确要求开始真机测试，当前由该对话执行sensors02限时SSC采样。
GPU175已完成日志回收并释放设备，APFS147；其他对话继续本地工作。候选提交a194e62，
启用nabu-slpi=2，状态见log/host/sensors-live-20261109/continuation.json。
本轮日志未回收前，不准备其他测试槽或启动其他候选；不额外重启Android。

最新用户要求GPU175取回日志后通知“传感器4”开始真机测试。GPU175已通过：启动前
就绪检查、64帧双路像素、复用、释放及用户动画/清除/桌面触摸正常。3,644,206字节
连续前缀和完整64MiB槽1已备份清空，APFS147；设备为Android，现交由“传感器4”使用，
其他对话仅继续本地工作。Hall02未启动的预备槽也已另行完整备份清理，不能复用其旧清单。
GPU状态见log/host/gpu-v175/continuation.json；以下设备归属均为历史记录。

最新用户已明确要求本对话开始第175轮GPU真机测试。设备为Android、USB连接、无线关闭；
Hall01完整64MiB槽已备份清空，Hall02未部署且用户要求等待。当前设备由GPU175使用，
其他对话继续本地工作。App专项CI42642911170成功，复用已实测display01内核及v173启动包，
无SLPI；不额外重启Android。状态见log/host/gpu-v175/continuation.json。

2026-11-09“霍尔开关2”hall01启动后自动返回Android，完整64MiB槽已备份清空，
只有开始记录、无运行日志正文。已确认GPIO9 NORTH地址误写为0x03109000，修正为
0x03909000并构建r3；重启原因仍待复测。用户最新要求仅继续本地工作，必须等用户
再次确认设备恢复后才能开展下一轮真机测试，不因ADB在线自行开始。hall02槽1已在
该要求前准备，回执log/host/hall-20261109/hall02/log-preparation-final/preparation.json，
修正候选尚未部署或启动。当前记录见log/host/hall-20261109/continuation.json。

2026-11-09第174轮64帧CAMetalLayer实测通过：GPU/IOSurface各65536像素0错，
两个表面各复用32次、64个呈现回调、导入2/2释放held0；用户确认动画、清除、桌面触摸。
17,211,006字节日志前缀及完整64MiB槽1备份清空，APFS146，设备已恢复Android。
首次App于22:24:55早于GPU约22:25:02就绪，发现失败且GPU命令0；新进程实测通过。
继续第175轮启动就绪检查：GPUInventory确认后再安装/打开App，进入UIKit前检查当前
boot插件挂载和AGX属性。不能把页面内等待当作清除原版Metal进程缓存。仍复用display01
内核、第173轮启动包，不启用SLPI。见analysis/nabu-metal-present-app-v175.md及各轮continuation.json。

2026-11-09“霍尔开关”对话用户已选择单独测试；传感器3先完成了sensors01启动。
用户随后说明仍在iPadOS、稍后恢复Android；霍尔候选等待恢复后先保全sensors01日志
再启动，尚未部署或改写任何日志槽。内核nabu-hall-20261109-r2、启动包
nabu-bootstrap-hall-20261109及CI42630476319均已就绪，iPadOS开合效果尚未实测。
仅验证GPIO9保护盖合上息屏/打开唤醒，独立于SLPI。内核与启动包已完成检查，
见docs/NABU-HALL.md及log/host/hall-20261109/continuation.json；实机状态以该记录为准。

用户最新澄清：传感器全部交给新对话“传感器3”；本对话继续GPU，不接手传感器修复。
第173轮统一实测已完成：正常UIKit App经CAMetalLayer显示红黄条纹和紫色方块，
用户确认图案、清除及两次息屏唤醒/触摸正常。GPU和实际IOSurface各1024像素0错，
命令Completed，清除后导入1/1释放、held0。presented回调已观察，但time/id均0，
不能当作硬件同步或全系统应用加速完成。组合源码e595e0e完整CI42627788010成功。
4,556,035字节日志前缀及完整64MiB槽1已备份清空，APFS144，用户已恢复Android。
下一项为多帧CAMetalLayer呈现、drawable复用及资源释放，保留第172前端和息屏基线。
见analysis/nabu-gpu-v173.md；以下候选状态为历史记录，以上述实际结果为准。

第173轮已按用户要求整合息屏、传感器诊断和GPU App：组合内核为
artifacts/nabu-display-sensors-integrated/kernel/kernel.native-apfs.macho，采用已实测
息屏基底，保留61个对象、替换入口并加SLPI，共63个（GPU37个）。实际分支、原组件
范围及正式加载器检查通过。启动包artifacts/nabu-bootstrap-combined-sensors包含
v173用户态和20个SLPI固件文件，APFS/读回通过；仅root挂载助手，无旧GPU探针任务。
App CI42621723942成功；配套42621723810因macOS执行器容量不足未运行两项作业，
不能称全套CI通过。统一配置使用slot1及nabu-slpi=1，旧v168绑定slot14不再用于本轮。
当前部署状态以log/host/gpu-v173/continuation.json为准。用户已授权报告齐全后统一测试。

2026-11-09“传感器2”已完成供“30”统一整合测试的SLPI诊断候选，未部署或启动。
交接见docs/NABU-SENSORS.md及log/host/sensors-20261109/handoff.json。
内核artifacts/nabu-sensors-ready-20261109/kernel/kernel.native-apfs.macho基于v168，
统一测试需以息屏修复的link-command重新组合；固件启动包已通过APFS检查和20文件读回。
Android四路SSC物理采样通过，气压/距离为空立即结束；后置BU27030的SSC缺物理标志，
不能据默认false判定硬件不存在。iPadOS仅准备PAS/SMP2P/GLINK/SSC服务发现诊断，
sensor_pd、实时采样及原生HID尚未完成，不能称传感器修复已通过。SMC不返回仍是实测风险。

2026-11-09息屏display01实机通过：用户确认背光完全熄灭，连续三次唤醒、亮度和
触摸正常。bcd4def完整CI42621253671通过，新内核为
artifacts/nabu-display-power-ready/kernel.native-apfs.macho（保留v168的62个服务/GPU对象）。
9次背光请求全部回读成功、bus-error0；3,462,248字节前缀及完整64MiB槽1已备份
清空，APFS143，设备已回Android。未额外重启Android。GPU下一轮可复用此内核，
但需新建对应日志清单，不能沿用绑定v168的slot14清单。面板支持120Hz，本轮只修
背光，未验证120Hz硬件同步或整机深睡。见docs/NABU-DISPLAY-POWER.md。

第173轮App源码19b5b728eaa61ffe3b909fb3d946e6d10d9fe7e2使用真实CAMetalLayer，
完成后双路像素核对再present。编译、签名、下载审查与单帧应用实测均已通过。

2026-11-09第172轮默认IOSurface复制兼容实机通过：Mach完整读回16KiB，32轮/64命令，
双向各32768像素及保护区0错，资源1/1释放、held0。pointer0、copied1、degraded1、
shadow1/in-place0，copy-in65920、merge-back13568字节；不等同零复制或桌面加速。
桌面触摸正常，3,309,688字节及64MiB槽备份清空，APFS142，未额外重启Android。
继续本机20F66 CAMetalLayer小型应用的drawable与呈现路径；保持v168内核和已合格
第172前端，先核对真实私有调用，不泛开cached imports。见analysis/nabu-gpu-v172.md。

2026-11-09第171轮默认IOSurface创建/标准工厂通过，BoMap Unsupported转OOM，
指针与复制计数全0、无GPU命令。实际派生runtime的copied.rs只为macOS启用Mach
read_pages，iOS走false分支；下一步补这一平台条件并实测Mach读回，cached imports
保持关闭。用户桌面触摸正常，3,572,008字节及64MiB槽备份清空，APFS141。

2026-11-09第170轮NC wrapped IOSurface实机通过：32轮/65命令，双向各32768像素，
保护区及生命周期像素错误0；真实16KiB导入1次，copy0、in-place1、shadow0，释放1/1、
held0及owner解除映射/释放通过。用户桌面触摸正常，3,364,841字节及64MiB槽备份
清空，APFS140。本轮未额外重启Android。继续普通系统IOSurface路径与呈现；当前
NC结果和测试进程工厂不能等同普通缓存表面、跨进程或桌面硬件加速完成。

第169轮后用户明确要求后续真机测试不再额外重启Android：恢复Android后直接回收、
部署并切bootloader临时启动，不执行额外adb reboot。此约束覆盖之前完整Android
重启的试验步骤，见docs/SPECIAL-STEPS.md第8条。

2026-11-09第169轮标准MTLCreateSystemDefaultDevice实机通过：真实AGX registry ID、
fill4096、compute1024、guards128、render1024/红256/其他0、padding4096，3个命令
缓冲Completed。只读插件挂载通过，用户桌面触摸正常；3,074,483字节及64MiB槽已
备份清空，APFS139。继续独立NC wrapped IOSurface共享导入、双向像素和释放测试；
工厂目前只准入测试进程，尚不表示桌面、IOSurface或应用硬件加速完成。

2026-11-09第168轮AGX发现服务、CP写入及ABI查询通过，桌面触摸正常；系统Metal
尚未调用：root插件挂载缺少com.apple.private.bindfs-allow而返回EPERM，probe
在ready检查后退出。3,339,280字节及64MiB日志槽备份清空，APFS138。下一轮仅补
挂载助手的专用签名权限，复用v168内核及已验证前端，继续标准工厂实测。

2026-11-09第167轮独立Metal实机通过：fill4096字节、compute1024字、128保护字，
render1024像素（红256、其他颜色0）、4096行间保护字节，3个命令缓冲全部Completed。
_MTLDevice运行时尺寸528吻合原版；实际RGBA和PNG已回收，用户桌面触摸正常并恢复
Android，4,356,279字节日志及64MiB槽备份清空，APFS137。继续新进程经标准
MTLCreateSystemDefaultDevice工厂的实测，再推进IOSurface和呈现；独立Metal不能
视为系统工厂、桌面或应用硬件加速已完成。

2026-11-09第166轮A640 Vulkan实机通过：fill1024/1024、compute1024/1024、
32x32三角形目标像素512且其他颜色0；用户桌面触摸正常并恢复Android，日志槽已备份
清空，APFS136。使用3bbeff9内核与CI42576001993的Vulkan程序。继续独立16.5 Metal
真实计算/绘图和系统接入；Vulkan通过不能视作系统Metal或应用加速已完成。
第165轮卡Logo发生于GPU90秒延迟前的ADSP未完成SMC续调；完整Android重启后，同一
内核/bootstrap在166通过。音频固件续调/清理问题单独保留，不误归因GPU BO策略。

2026-11-09第163轮A640离屏2D光栅已通过：32x16图案512/512像素，保护区0错误，
fence2/2及正常停止；用户确认桌面触摸正常并恢复Android，日志和实际图案已回收。
继续最小Vulkan计算/三角形及20F66 Metal接入；2D通过不能等同3D或应用加速通过。

2026-11-09第162轮已验证A640真实CP内存写入0x6401cafe、fence 1/1及CP/GMU正常停止；
用户确认桌面和触摸正常，恢复Android后日志已备份清空，APFS132。继续第163轮离屏
光栅图案/像素读回，随后3D与20F66 Metal接入。不要把CP成功等同应用硬件加速完成。

2026-11-09第161轮后，用户确认桌面、Spotlight搜索键盘及输入正常，并手动恢复Android，
下一项选择GPU。先核对现有A640硬件后端与20F66图形接口，再分阶段验证真实GPU执行、
渲染和系统接入；保留已通过的音频与桌面基线。视频解码/IOSurface/显示问题分别记录，
不能把GPU服务发布或返回成功当成硬件加速完成。

2026-11-08第135轮后，用户明确同意开始音频修复：先原生音频服务/路由与蓝牙耳机实际播放，再内置扬声器和麦克风；传感器后置。Wi-Fi联网与信号格已通过，自动重连继续保留待修。以下早期无线优先级为历史背景，以本段最新指令为准。

第138轮用户确认蓝牙耳机本地左右声道、Safari持续声音及蓝牙关闭/开启后重连播放均正常。下一项按上述顺序推进内置扬声器与麦克风。Safari哔哩哔哩视频区域黑屏、播放时闪烁单独留待图形/视频链路排查，不能将GPU视为已确定的唯一原因，也不能把音频通过等同视频通过。

当前任务遵循[基本技术路线](docs/BASIC-TECHNICAL-ROADMAP.md)。用户于2026-11-06在第75轮验收后明确开始修复Wi-Fi和蓝牙；当前优先推进这两项硬件驱动，未完成的软件验收继续保留记录。仅接管已分配给iPadOS的64GiB区域，继续使用APFS并保留现有持久化成果。

用户在第95轮接续中明确要求Wi-Fi和蓝牙并行推进，不等待一项完全修复才开始另一项；每轮分别保留真实硬件与原生服务验证结果。

开展或接续任务前，阅读并遵循 [特殊步骤清单](docs/SPECIAL-STEPS.md)。这是用户明确指定的项目规则。

- 访问和下载走本地代理：`http://127.0.0.1:19999`。
- 本地无法反编译的任务走 GitHub Actions。
- 文件只在下载时审查一次，后续不重复审查或进行哈希审计。
- 不进行防御性编程，围绕实际需求和已出现的错误直接修改。

