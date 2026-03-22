"""
Test CoolProp behavior on Mac (arm64) to identify segfault triggers.
"""
import CoolProp.CoolProp as CP
import platform
import sys

print(f"Python: {sys.version}")
print(f"Platform: {platform.platform()}")
print(f"CoolProp: {CP.__version__ if hasattr(CP, '__version__') else 'unknown'}")
print()

fluids_to_test = [
    'R1233zd(E)', 'R245fa', 'R1234ze(E)', 'R1234ze(Z)',
    'R227ea', 'R236fa', 'R600a', 'R717', 'R744',
]

print("=== PropsSI basic tests ===")
for fluid in fluids_to_test:
    try:
        h = CP.PropsSI('H', 'T', 350, 'P', 1e5, fluid)
        Tc = CP.PropsSI('Tcrit', fluid)
        print(f"  {fluid}: H={h:.0f} J/kg, Tc={Tc-273.15:.1f}C  OK")
    except Exception as e:
        print(f"  {fluid}: FAIL - {e}")

print()
print("=== TTSE backend test ===")
for fluid in ['R1233zd(E)', 'R245fa', 'R1234ze(E)']:
    try:
        AS = CP.AbstractState('TTSE&HEOS', fluid)
        AS.update(CP.PT_INPUTS, 1e5, 350)
        h = AS.hmass()
        print(f"  {fluid} TTSE: H={h:.0f} J/kg  OK")
    except Exception as e:
        print(f"  {fluid} TTSE: FAIL - {e}")

print()
print("=== High-pressure TTSE test (near critical) ===")
for fluid in ['R1233zd(E)', 'R245fa']:
    try:
        Tc = CP.PropsSI('Tcrit', fluid)
        Pc = CP.PropsSI('Pcrit', fluid)
        # Test near critical point
        T_test = Tc * 0.95
        P_test = Pc * 0.5
        h = CP.PropsSI('H', 'T', T_test, 'P', P_test, fluid)
        print(f"  {fluid} near-critical: T={T_test-273.15:.1f}C, P={P_test/1e5:.1f}bar, H={h:.0f}  OK")
    except Exception as e:
        print(f"  {fluid} near-critical: FAIL - {e}")

print()
print("All tests completed without crash.")
