
/mnt/d/github-IOS/XIAOMI_PAD5-NABU/log/host/display-v16/QuartzCore.text.elf:	file format elf64-littleaarch64

Disassembly of section .text:

00000001881fb000 <.text>:
188433470: a9bb67fa    	stp	x26, x25, [sp, #-0x50]!
188433474: a9015ff8    	stp	x24, x23, [sp, #0x10]
188433478: a90257f6    	stp	x22, x21, [sp, #0x20]
18843347c: a9034ff4    	stp	x20, x19, [sp, #0x30]
188433480: a9047bfd    	stp	x29, x30, [sp, #0x40]
188433484: 910103fd    	add	x29, sp, #0x40
188433488: aa0703f7    	mov	x23, x7
18843348c: aa0603f8    	mov	x24, x6
188433490: aa0503f5    	mov	x21, x5
188433494: aa0403e9    	mov	x9, x4
188433498: aa0103f3    	mov	x19, x1
18843349c: aa0003f4    	mov	x20, x0
1884334a0: f02a3f48    	adrp	x8, 0x1dcc1e000 <.text+0x54a23000>
1884334a4: f941d500    	ldr	x0, [x8, #0x3a8]
1884334a8: 2a0203e8    	mov	w8, w2
1884334ac: 2a0303e4    	mov	w4, w3
1884334b0: aa0903e2    	mov	x2, x9
1884334b4: aa0803e3    	mov	x3, x8
1884334b8: 52800005    	mov	w5, #0x0                // =0
1884334bc: 94044ff9    	bl	0x1885474a0 <.text+0x34c4a0>
1884334c0: aa0003f6    	mov	x22, x0
1884334c4: aa1303e0    	mov	x0, x19
1884334c8: 955c145e    	bl	0x18db38640 <.text+0x593d640>
1884334cc: aa0003f9    	mov	x25, x0
1884334d0: 52800001    	mov	w1, #0x0                // =0
1884334d4: 52800002    	mov	w2, #0x0                // =0
1884334d8: 97f8786b    	bl	0x188251684 <.text+0x56684>
1884334dc: aa0003fa    	mov	x26, x0
1884334e0: 902cbb48    	adrp	x8, 0x1e1b9b000 <.text+0x599a0000>
1884334e4: f945f108    	ldr	x8, [x8, #0xbe0]
1884334e8: b100051f    	cmn	x8, #0x1
1884334ec: 540006a1    	b.ne	0x1884335c0 <.text+0x2385c0>
1884334f0: 6b19035f    	cmp	w26, w25
1884334f4: 54000160    	b.eq	0x188433520 <.text+0x238520>
1884334f8: 902cbb48    	adrp	x8, 0x1e1b9b000 <.text+0x599a0000>
1884334fc: 395ea109    	ldrb	w9, [x8, #0x7a8]
188433500: 34000109    	cbz	w9, 0x188433520 <.text+0x238520>
188433504: 395ea108    	ldrb	w8, [x8, #0x7a8]
188433508: 7100011f    	cmp	w8, #0x0
18843350c: 121e7b08    	and	w8, w24, #0xfffffffd
188433510: 7a411900    	ccmp	w8, #0x1, #0x0, ne
188433514: 52800088    	mov	w8, #0x4                // =4
188433518: 9a9f0102    	csel	x2, x8, xzr, eq
18843351c: 14000004    	b	0x18843352c <.text+0x23852c>
188433520: 7100131f    	cmp	w24, #0x4
188433524: 540005a2    	b.hs	0x1884335d8 <.text+0x2385d8>
188433528: 2a1803e2    	mov	w2, w24
18843352c: f9400bb8    	ldr	x24, [x29, #0x10]
188433530: aa1603e0    	mov	x0, x22
188433534: 94044aa3    	bl	0x188545fc0 <.text+0x34afc0>
188433538: aa1603e0    	mov	x0, x22
18843353c: 52800022    	mov	w2, #0x1                // =1
188433540: 94044828    	bl	0x1885455e0 <.text+0x34a5e0>
188433544: 340000d7    	cbz	w23, 0x18843355c <.text+0x23855c>
188433548: aa1603e0    	mov	x0, x22
18843354c: 52800022    	mov	w2, #0x1                // =1
188433550: 9404473c    	bl	0x188545240 <.text+0x34a240>
188433554: 52800082    	mov	w2, #0x4                // =4
188433558: 14000002    	b	0x188433560 <.text+0x238560>
18843355c: f9400fa2    	ldr	x2, [x29, #0x18]
188433560: aa1603e0    	mov	x0, x22
188433564: 94044c4f    	bl	0x1885466a0 <.text+0x34b6a0>
188433568: b40000f5    	cbz	x21, 0x188433584 <.text+0x238584>
18843356c: aa1603e0    	mov	x0, x22
188433570: 52800022    	mov	w2, #0x1                // =1
188433574: 94044703    	bl	0x188545180 <.text+0x34a180>
188433578: aa1603e0    	mov	x0, x22
18843357c: aa1503e2    	mov	x2, x21
188433580: 94044a80    	bl	0x188545f80 <.text+0x34af80>
188433584: aa1403e0    	mov	x0, x20
188433588: aa1603e2    	mov	x2, x22
18843358c: aa1303e3    	mov	x3, x19
188433590: d2800004    	mov	x4, #0x0                // =0
188433594: 94043eb3    	bl	0x188543060 <.text+0x348060>
188433598: aa0003f3    	mov	x19, x0
18843359c: aa1803e2    	mov	x2, x24
1884335a0: 94044830    	bl	0x188545660 <.text+0x34a660>
1884335a4: aa1303e0    	mov	x0, x19
1884335a8: a9447bfd    	ldp	x29, x30, [sp, #0x40]
1884335ac: a9434ff4    	ldp	x20, x19, [sp, #0x30]
1884335b0: a94257f6    	ldp	x22, x21, [sp, #0x20]
1884335b4: a9415ff8    	ldp	x24, x23, [sp, #0x10]
1884335b8: a8c567fa    	ldp	x26, x25, [sp], #0x50
1884335bc: d65f03c0    	ret
1884335c0: 902cbb40    	adrp	x0, 0x1e1b9b000 <.text+0x599a0000>
1884335c4: 912f8000    	add	x0, x0, #0xbe0
1884335c8: d0269e41    	adrp	x1, 0x1d57fd000 <.text+0x4d602000>
1884335cc: 9101a021    	add	x1, x1, #0x68
1884335d0: 940257cf    	bl	0x1884c950c <.text+0x2ce50c>
1884335d4: 17ffffc7    	b	0x1884334f0 <.text+0x2384f0>
1884335d8: 955c1537    	bl	0x18db38ab4 <.text+0x593dab4>
