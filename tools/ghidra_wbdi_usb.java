// Ghidra headless: find and decompile code related to USB/MOC command handling
// in MicroarrayMocWbdi.dll.  Strings are located by scanning memory (they are
// not necessarily defined as Data), then all referencing functions are
// decompiled and printed.
// @category Analysis

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import ghidra.app.decompiler.*;
import java.util.*;

public class WbdiUsb2 extends GhidraScript {
    DecompInterface dec;

    static final String[] NEEDLES = {
        "Realtek USB2.0 Finger Print Bridge",
        "WINUSB",
        "%s:%d] CRC failed",
        "detect mode",
        "set register",
        "sensor_create",
        "mafp",
    };

    @Override
    public void run() throws Exception {
        dec = new DecompInterface();
        dec.openProgram(currentProgram);

        Memory mem = currentProgram.getMemory();
        Listing lst = currentProgram.getListing();
        ReferenceManager rm = currentProgram.getReferenceManager();
        List<Address> hits = new ArrayList<>();

        // scan memory for ascii and utf16 versions
        for (String n : NEEDLES) {
            hits.clear();
            scanFor(mem, n.getBytes("US-ASCII"), hits);
            scanFor(mem, utf16(n), hits);
            println("### needle '" + n + "' -> " + hits.size() + " location(s)");
            Set<Function> funcs = new LinkedHashSet<>();
            for (Address a : hits) {
                println("   @ " + a);
                for (Reference r : rm.getReferencesTo(a)) {
                    Function f = lst.getFunctionContaining(r.getFromAddress());
                    if (f != null) {
                        println("      xref " + r.getFromAddress() + " in " + f.getName());
                        funcs.add(f);
                    } else {
                        println("      xref " + r.getFromAddress() + " (no function)");
                    }
                }
            }
            for (Function f : funcs) {
                println("=== DECOMP " + f.getName() + " @ " + f.getEntryPoint() + " ===");
                DecompileResults res = dec.decompileFunction(f, 90, monitor);
                if (res != null && res.decompileCompleted())
                    println(res.getDecompiledFunction().getC());
                else
                    println("   (decompile failed)");
            }
        }
    }

    static byte[] utf16(String s) {
        byte[] o = new byte[s.length() * 2];
        for (int i = 0; i < s.length(); i++) {
            o[i * 2] = (byte) (s.charAt(i) & 0xff);
            o[i * 2 + 1] = (byte) ((s.charAt(i) >> 8) & 0xff);
        }
        return o;
    }

    void scanFor(Memory mem, byte[] pat, List<Address> out) throws Exception {
        Address start = mem.getMinAddress();
        Address cur = start;
        while (cur != null) {
            Address found = mem.findBytes(cur, pat, null, true, monitor);
            if (found == null) break;
            out.add(found);
            cur = found.add(1);
            if (out.size() > 40) break;
        }
    }
}
