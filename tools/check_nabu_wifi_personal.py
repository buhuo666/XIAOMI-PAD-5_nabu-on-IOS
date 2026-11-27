"""Actual-source personal security tests used by the common Wi-Fi checker."""
import json,shutil,subprocess
from pathlib import Path
from check_nabu_wifi_security import unit,extract_function,unique,ROOT
from check_darwinboot_8796 import host_command,host_path

def replay(out,control,backend):
    fixture=ROOT/'tools/fixtures/nabu_wifi_security';variants=[]
    if control:
        host=(fixture/'control_host.h').read_text()
        # Keep host SDK declarations separate from named allocation peers.
        host=host.replace('typedef uintptr_t user_addr_t;', '#define user_addr_t nabu_fixture_user_addr_t\ntypedef uintptr_t user_addr_t;')
        host=host.replace('static int memset_s(', '#define memset_s nabu_fixture_memset_s\nstatic int memset_s(')
        (out/'control_host.h').write_text(host)
        (out/'control_replay.c').write_text((fixture/'control_modes_replay.c').read_text())
        code,_=unit(out,'control',control,[('request',r'^struct apple80211req \{.*?^\};'),
            ('association',r'^struct apple80211_assoc \{.*?^\};'),('PMK',r'^#define CIPHER_PMK[^\n]+'),
            ('passphrase',r'^#define CIPHER_PASSPHRASE[^\n]+'),('ABI',r'^_Static_assert\(sizeof\(struct apple80211_assoc\).*?;')],
            ('join_rsn_diagnostic','join_security','set_join'))
        variants.append(('personal-control',code,control.parents[1]))
    if backend:
        source=backend.read_text();chunks=[(fixture/'backend_host.h').read_text()]
        for pattern in [r'^#define ELEMENTS_MOST[^\n]+',r'^struct lx_target \{.*?^\};',r'^static const uint8_t wmm\[4\][^\n]+']:
            chunks.append(unique(source,pattern)[0])
        chunks.append((fixture/'joint_host.h').read_text().replace('bool sae, h2e;',
            'bool sae, h2e;\n    struct hakios_security_choice security;'))
        for function in ('channel_of','element','vendor_element','protection','request_elements'):
            chunks.append(extract_function(source,function)[0])
        chunks.append((fixture/'backend_modes_replay.c').read_text());code=out/'actual-personal-backend.c'
        code.write_text('\n'.join(chunks),newline='\n')
        variants.append(('personal-backend',code,backend.parents[3]/'xnu/files/bsd'))
    results=[]
    for name,code,headers in variants:
        # Only the two real station contract headers belong in this host
        # replay. Adding all XNU BSD headers would shadow the macOS SDK's
        # unrelated sys/cdefs.h and sys/types.h.
        isolated=out/(name+'-headers');(isolated/'sys').mkdir(parents=True,exist_ok=True)
        for header in ('hakios.sta.h','hakios.security.h'):
            shutil.copyfile(headers/'sys'/header,isolated/'sys'/header)
        for kind,flags in [('release',['-O2']),('sanitized',['-g','-fsanitize=address,undefined','-fno-sanitize-recover=all'])]:
            exe=out/(name+'-'+kind)
            compiler='clang' if __import__('sys').platform=='darwin' else 'clang-18'
            cmd=[compiler,'-std=gnu11','-Wall','-Wextra','-Werror','-DLX_HAVE_SAE',*flags,'-I'+host_path(out),'-I'+host_path(isolated),host_path(code),'-o',host_path(exe)]
            p=subprocess.run(host_command(cmd),capture_output=True);(out/(exe.name+'-compile.log')).write_bytes(p.stdout+p.stderr)
            if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace'))
            p=subprocess.run(host_command([host_path(exe)]),capture_output=True);(out/(exe.name+'.log')).write_bytes(p.stdout+p.stderr)
            results.append(dict(variant=name,kind=kind,returncode=p.returncode,summary=p.stdout.decode(errors='replace').strip()))
            if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    report=dict(hardware_tested=False,passed=True,control_source=str(control),backend_source=str(backend),results=results,
        actual_source_extracted=True,station_abi_bytes=144)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
