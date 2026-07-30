import com.romraider.maps.*;
import com.romraider.xml.DOMRomUnmarshaller;
import org.w3c.dom.*;
import javax.xml.parsers.*;
import java.io.*;
import java.nio.file.*;

/**
 * Verifies that RomRaider does not merely ACCEPT the 3D tables, but reads the
 * correct values out of them.
 *
 * For every 3D table it compares RomRaider's own cell values against the raw
 * big-endian uint16 at the address the definition declares. "faulty=0" only
 * proves the table was constructed; this proves the data is interpreted right.
 */
public class Verify3D {
    public static void main(String[] a) throws Exception {
        System.setProperty("java.awt.headless", "false");
        // Testing mode makes populateTables print stack traces instead of opening
        // a modal "error loading table" dialog, which otherwise blocks forever.
        com.romraider.util.SettingsManager.setTesting(true);
        File defFile = new File(a[0]);
        byte[] rom = Files.readAllBytes(Paths.get(a[1]));

        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(false);
        Document doc = f.newDocumentBuilder().parse(defFile);
        Node root = doc.getDocumentElement();
        DOMRomUnmarshaller u = new DOMRomUnmarshaller();
        Node match = u.checkDefinitionMatch(root, rom);
        if (match == null) { System.out.println("NO MATCH"); return; }
        Rom r = u.unmarshallXMLDefinition(defFile, root, match, rom,
                    new com.romraider.swing.JProgressPane());
        // unmarshalling only builds table shells; this is what reads the bytes
        System.out.println("unmarshalled OK, tables=" + r.getTables().size());
        System.out.flush();
        System.out.println("calling populateTables..."); System.out.flush();
        r.populateTables(rom, new com.romraider.swing.JProgressPane());
        System.out.println("populateTables returned"); System.out.flush();

        int tables=0, cells=0, bad=0;
        StringBuilder firstBad = new StringBuilder();
        for (Table t : r.getTables()) {
            if (!(t instanceof Table3D)) continue;
            Table3D t3 = (Table3D) t;
            DataCell[][] d = t3.get3dData();
            tables++;
            int base = t.getStorageAddress();
            int sx = t3.getSizeX(), sy = t3.getSizeY();
            for (int y=0; y<sy; y++) {
                for (int x=0; x<sx; x++) {
                    // definition declares row-major uint16 big-endian
                    int off = base + (y*sx + x)*2;
                    int expect = ((rom[off]&0xFF)<<8) | (rom[off+1]&0xFF);
                    int got = (int) d[x][y].getBinValue();
                    cells++;
                    if (got != expect) {
                        bad++;
                        if (firstBad.length()==0)
                            firstBad.append(String.format(
                              "%s [x=%d,y=%d] rom@0x%06X=%d but RomRaider=%d",
                              t.getName(), x, y, off, expect, got));
                    }
                }
            }
        }
        System.out.printf("%-40s 3D tables=%d cells=%d mismatched=%d%n",
                new File(a[1]).getName(), tables, cells, bad);
        if (bad>0) System.out.println("   first mismatch: "+firstBad);
        else System.out.println("   every 3D cell matches the raw ROM bytes");
    }
}
