/* Host-only differential harness. The build script places the actual old and
 * new argument functions immediately before this file, not simplified copies.
 */
static unsigned random_state=0x4e414255, parser_cases, exec_cases;
static unsigned random_word(void) { random_state=random_state*1664525u+1013904223u; return random_state; }

static void parser_compare(const char *configuration,const char *name,size_t size) {
    struct guarded { unsigned char before[16]; char data[520]; unsigned char after[16]; } old,new;
    memset(&old,0xa5,sizeof(old)); memset(&new,0xa5,sizeof(new));
    strcpy(exec_inject_conf,configuration);
    struct nameidata nd={.ni_cnd={.cn_nameptr=(char *)name,.cn_namelen=(int)strlen(name)}};
    struct image_params image={.ip_ndp=&nd};
    bool a=legacy_exec_inject_env(&image,old.data,size);
    bool b=nabu_exec_injection_env(configuration,name,strlen(name),new.data,size);
    assert(a==b && !memcmp(&old,&new,sizeof(old)));
    parser_cases++;
}

static void parser_expected(const char *configuration,const char *name,const char *expected,size_t size) {
    char output[512]; memset(output,0xa5,sizeof(output));
    bool matched=nabu_exec_injection_env(configuration,name,strlen(name),output,size);
    assert(matched==(expected!=NULL));
    if (expected) assert(!strcmp(output,expected));
    parser_cases++;
}

static void parser_tests(void) {
    const char *configs[]={"","/a A","/a A B;/b B","/a A;/a A","/a ; /b A;;", ";;  /a A  B; /c C  "};
    const char *names[]={"","A","B","C","AB","/a"};
    for(unsigned c=0;c<sizeof(configs)/sizeof(configs[0]);c++)
        for(unsigned n=0;n<sizeof(names)/sizeof(names[0]);n++)
            for(size_t size=0;size<=512;size++) parser_compare(configs[c],names[n],size);
    for(unsigned i=0;i<20000;i++) {
        static const char alphabet[]="/libabcABC123. ;";
        char conf[4096],name[30];
        size_t length=random_word()%4096;
        for(size_t j=0;j<length;j++) conf[j]=alphabet[random_word()%(sizeof(alphabet)-1)];
        conf[length]=0;
        size_t n=random_word()%sizeof(name);
        for(size_t j=0;j<n;j++) name[j]=alphabet[random_word()%(sizeof(alphabet)-1)];
        name[n]=0;
        parser_compare(conf,name,random_word()%513);
    }
    parser_expected("/a *","App","DYLD_INSERT_LIBRARIES=/a",512);
    parser_expected("/a exact *;/b other;/c * exact","exact","DYLD_INSERT_LIBRARIES=/a:/c",512);
    parser_expected("/a exact *;/b other;/c * exact","unlisted","DYLD_INSERT_LIBRARIES=/a:/c",512);
    parser_expected("/a prefix*","prefix-long",NULL,512);
    parser_expected("/a *","",NULL,512);
    parser_expected("/a *","App",NULL,25);
    parser_expected("/a *","App","DYLD_INSERT_LIBRARIES=/a",26);
    char longconfig[4096]; memset(longconfig,'x',4000); memcpy(longconfig+4000," *;/short *",12);
    parser_expected(longconfig,"App","DYLD_INSERT_LIBRARIES=/short",512);
    assert(!nabu_exec_injection_env("/a *",NULL,0,longconfig,512));
}

static void init_image(struct image_params *image,char *output,unsigned bits,unsigned interpreter,
    unsigned capacity,unsigned argspace,struct nameidata *nd) {
    memset(image,0,sizeof(*image)); memset(output,0xcc,8192);
    image->ip_ndp=nd;
    image->ip_flags=((bits&1)?IMGPF_WAS_64BIT_ADDR:0)|((bits&2)?IMGPF_IS_64BIT_ADDR:0)|
        (interpreter?IMGPF_INTERPRET:0);
    unsigned ptr=(bits&1)?8:4;
    image->ip_user_argv=(user_addr_t)(uintptr_t)(arena+0);
    image->ip_user_envv=(user_addr_t)(uintptr_t)(arena+64);
    image->ip_user_fname=(user_addr_t)(uintptr_t)(arena+256);
    image->ip_strspace=(int)capacity; image->ip_argspace=(int)argspace;
    image->ip_strendp=output; image->ip_interp_sugid_fd=interpreter==2?37:-1;
    strcpy(image->ip_interp_buffer,"/bin/sh  -e\targument");
    image->ip_seg=UIO_USERSPACE;
    memset(arena,0,1024);
    strcpy((char *)arena+256,"/test/script"); strcpy((char *)arena+320,"arg0");
    strcpy((char *)arena+400,"a long second argument");
    strcpy((char *)arena+480,"PATH=/var/jb/bin"); strcpy((char *)arena+560,"CUSTOM=plain");
    uint64_t argv[]={ (uintptr_t)(arena+320),(uintptr_t)(arena+400),0 };
    uint64_t envv[]={ (uintptr_t)(arena+480),(uintptr_t)(arena+560),0 };
    for(unsigned i=0;i<3;i++) { memcpy(arena+i*ptr,&argv[i],ptr); memcpy(arena+64+i*ptr,&envv[i],ptr); }
}

static long position(char *value,char *base) { return value?value-base:-1; }

static void exec_compare(unsigned bits,unsigned interpreter,unsigned capacity,unsigned argspace,
    int fail_copy,int fail_string) {
    struct image_params a,b; char outa[8192],outb[8192];
    struct nameidata nd={.ni_cnd={.cn_nameptr="TestApp",.cn_namelen=7}};
    init_image(&a,outa,bits,interpreter,capacity,argspace,&nd);
    init_image(&b,outb,bits,interpreter,capacity,argspace,&nd);
    copyin_calls=string_calls=0; fail_copyin_at=fail_copy; fail_string_at=fail_string;
    int old=legacy_exec_extract_strings(&a);
    copyin_calls=string_calls=0;
    int candidate=nabu_exec_extract_strings(&b);
    assert(old==candidate && a.ip_argc==b.ip_argc && a.ip_envc==b.ip_envc);
    assert(a.ip_strspace==b.ip_strspace && a.ip_argspace==b.ip_argspace);
    assert(position(a.ip_strendp,outa)==position(b.ip_strendp,outb));
    assert(position(a.ip_startargv,outa)==position(b.ip_startargv,outb));
    assert(position(a.ip_endargv,outa)==position(b.ip_endargv,outb));
    assert(position(a.ip_endenvv,outa)==position(b.ip_endenvv,outb));
    assert(!memcmp(outa,outb,sizeof(outa)) && !memcmp(a.ip_interp_buffer,b.ip_interp_buffer,sizeof(a.ip_interp_buffer)));
    exec_cases++;
}

int main(void) {
    arena=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0);
    assert(arena!=MAP_FAILED && (uintptr_t)arena+4096<=UINT32_MAX);
    parser_tests();
    const char *configuration[]={"","/a TestApp","/a TestApp;/b Other;/c TestApp"};
    const unsigned capacities[]={4,8,12,20,31,64,96,128,192,512,8192};
    for(unsigned conf=0;conf<3;conf++) for(unsigned bits=0;bits<4;bits++)
        for(unsigned interp=0;interp<3;interp++) for(unsigned c=0;c<sizeof(capacities)/sizeof(capacities[0]);c++)
            for(unsigned log=0;log<3;log++) for(unsigned fault=0;fault<10;fault++) {
                strcpy(exec_inject_conf,configuration[conf]); exec_applog=log;
                strcpy(exec_applog_name,log==1?"Other,Test":"");
                exec_compare(bits,interp,capacities[c],capacities[c],fault,-1);
                exec_compare(bits,interp,8192,capacities[c],-1,fault);
            }
    fail_copyin_at=fail_string_at=-1; copyin_calls=string_calls=0;
    strcpy(exec_inject_conf,"/a *;/b TestApp"); exec_applog=0;
    struct image_params image; char output[8192];
    struct nameidata nd={.ni_cnd={.cn_nameptr="TestApp",.cn_namelen=7}};
    init_image(&image,output,3,0,8192,8192,&nd);
    assert(nabu_exec_extract_strings(&image)==0 && image.ip_argc==2 && image.ip_envc==3);
    char *env=image.ip_endargv; env+=strlen(env)+1; env+=strlen(env)+1;
    assert(!strcmp(env,"DYLD_INSERT_LIBRARIES=/a:/b"));
    munmap(arena,4096);
    printf("{\"parser_cases\":%u,\"exec_argument_cases\":%u,\"wildcard_exec_case\":true,\"device_executed\":false}\n",parser_cases,exec_cases);
    return 0;
}
