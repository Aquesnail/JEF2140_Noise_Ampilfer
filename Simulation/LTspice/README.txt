本包对应你上传的 Vitual_GND_fixed_cascode_trans.net，包括主放大器 U5、尾电流控制运放 U1、真实虚拟地缓冲器 U10。

使用：
1. 解压到现有工程目录，旁边应已有原来的 BCM847.lib、jfex140.lib、OPA161x.LIB。
2. 打开 virtual_three_opa_op_check.net，运行 .op。所有供电已改为最终直流 10 V，输入暂态激励停用。原始原理图和模型没有改动。
3. 本文件加载 virtual_dc_seed_three_opa.txt，成功后保存 LTspice 原生偏置 virtual_native_three_opa_bias.txt。
4. 再打开 virtual_three_opa_ac_check.net 可进行交流分析。输入 V2 为 AC 1。确认原生偏置已生成后，可把其中的 .loadbias 改为加载 virtual_native_three_opa_bias.txt。
5. 输出相对虚拟地的传递函数可查看 V(OUT,VGND)/V(VIN,VGND)。如果实际测量相对系统地，查看相应的 V(OUT) 即可，两种参考应区分。

验证范围：
已在 ngspice 44.2 中使用全部三颗完整 OPA161x 模型求直流解，并对导出的实际节点初值复核。仅对 PSpice 开关和 TABLE 语法做辅助兼容转换，没有把 U1 或 U10 替换为理想运放。最终须由 LTspice 用原始模型重新收敛；尚未声称通过原生 LTspice 验证。
种子文件仅提供节点电压初值，不强制节点电压。
本包不用于复现原上电过程；用户提供的原始上电网表保持原样。
节点编号与器件实例名变化后，需重新生成或核对初值。
