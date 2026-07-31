import com.romraider.maps.*;
import com.romraider.util.SettingsManager;
import com.romraider.xml.DOMRomUnmarshaller;
import com.romraider.swing.JProgressPane;
import org.w3c.dom.Node;
import javax.xml.parsers.DocumentBuilderFactory;
import java.io.File;
import java.nio.file.*;

/**
 * The test that actually matters for flashing: edit a table through the real
 * editor write path, save through the real save path, and leave the bytes for an
 * independent checker to judge.
 *
 * Everything else this project runs on the checksum proves the checksum code is
 * self-consistent. That is not the same as proving a ROM which came OUT of the
 * application is one the TCU will accept. This drives Rom.saveFile(), which is
 * what the Save button calls.
 *
 * Every image is done in one JVM against one parse of the definition. Parsing a
 * 3 MB definition once per image made this look hung when it was only slow.
 *
 *   EndToEndChecksum <def.xml> <out-dir> <rom.bin>...
 */
public class EndToEndChecksum {

    public static void main(String[] a) throws Exception {
        SettingsManager.setTesting(true);
        final File defFile = new File(a[0]);
        final Path outDir = Paths.get(a[1]);
        Files.createDirectories(outDir);

        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(false);
        final Node root = f.newDocumentBuilder().parse(defFile).getDocumentElement();

        int bad = 0;
        for (int i = 2; i < a.length; i++) {
            File romFile = new File(a[i]);
            String name = romFile.getName().replaceAll("\\.bin$", "");
            System.out.println("=== " + name);
            try {
                byte[] rom = Files.readAllBytes(romFile.toPath());
                DOMRomUnmarshaller u = new DOMRomUnmarshaller();
                Node match = u.checkDefinitionMatch(root, rom);
                if (match == null) { System.out.println("  NO DEFINITION MATCH"); bad++; continue; }

                Rom r = u.unmarshallXMLDefinition(defFile, root, match, rom, new JProgressPane());
                r.populateTables(rom, new JProgressPane());
                System.out.println("  validate as loaded: " + r.validateChecksum()
                        + " of " + r.getTotalAmountOfChecksums());

                // Scan every table for a writable cell rather than assuming a
                // particular one exposes cells - locked and placeholder-only
                // tables have none, and which those are varies by firmware.
                Table target = null;
                DataCell cell = null;
                outer:
                for (Table t : r.getTables()) {
                    DataCell[] cells = t.getData();
                    if (cells == null) continue;
                    for (DataCell c : cells) {
                        if (c != null && c.getStaticText() == null) {
                            target = t; cell = c; break outer;
                        }
                    }
                }
                if (cell == null) { System.out.println("  no writable cell"); bad++; continue; }

                double before = cell.getRealValue();
                cell.setRealValue(String.valueOf(before + 1.0));
                System.out.println("  edited \"" + target.getName() + "\": "
                        + before + " -> " + cell.getRealValue());

                byte[] saved = r.saveFile();
                Files.write(outDir.resolve(name + ".bin"), saved);
                System.out.println("  saved " + saved.length + " bytes; validate after: "
                        + r.validateChecksum() + " of " + r.getTotalAmountOfChecksums());
            } catch (Throwable t) {
                Throwable c = t;
                while (c.getCause() != null) c = c.getCause();
                System.out.println("  THREW " + c);
                bad++;
            }
        }
        System.out.println("\n" + (bad == 0 ? "all images saved" : bad + " image(s) failed"));
        System.exit(bad == 0 ? 0 : 1);
    }
}
