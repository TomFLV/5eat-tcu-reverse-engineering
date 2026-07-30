import com.romraider.maps.*;
import com.romraider.swing.ShiftCurveEditor;
import com.romraider.xml.DOMRomUnmarshaller;
import org.w3c.dom.*;
import javax.imageio.ImageIO;
import javax.swing.*;
import javax.xml.parsers.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.nio.file.*;

/**
 * Renders the shift curve editor to a PNG, and exercises an edit through it.
 *
 * The editor is the one part of this work whose whole point is how it looks, so
 * "it compiles" proves nothing. This draws it exactly as the GUI would, then
 * moves a vertex the way a drag does and confirms the change reached the ROM
 * bytes - a chart that draws beautifully but writes nowhere would look identical.
 *
 *   RenderCurveEditor <def.xml> <rom.bin> <out.png>
 */
public class RenderCurveEditor {
    public static void main(String[] a) throws Exception {
        System.setProperty("romraider.theme", "dark");
        com.romraider.util.SettingsManager.setTesting(true);
        com.romraider.swing.LookAndFeelManager.initLookAndFeel();

        File defFile = new File(a[0]);
        byte[] rom = Files.readAllBytes(Paths.get(a[1]));
        File out = new File(a[2]);

        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(false);
        Document doc = f.newDocumentBuilder().parse(defFile);
        Node root = doc.getDocumentElement();
        DOMRomUnmarshaller u = new DOMRomUnmarshaller();
        Node match = u.checkDefinitionMatch(root, rom);
        if (match == null) { System.out.println("NO MATCH"); return; }
        Rom r = u.unmarshallXMLDefinition(defFile, root, match, rom,
                    new com.romraider.swing.JProgressPane());
        r.populateTables(rom, new com.romraider.swing.JProgressPane());

        Table3D map = null;
        for (Table t : r.getTables()) {
            if (t instanceof Table3D && "Shift Map".equals(t.getName())) {
                map = (Table3D) t;
                break;
            }
        }
        if (map == null) { System.out.println("no Shift Map table"); return; }

        // What the ROM holds for the first real cell, before anything touches it.
        DataCell probe = null;
        int probeCol = -1;
        for (int c = 0; c < map.getSizeX() && probe == null; c++) {
            DataCell cell = map.get3dData()[c][0];
            if (cell != null && cell.getStaticText() == null && cell.getRealValue() > 0) {
                probe = cell;
                probeCol = c;
            }
        }
        System.out.printf("probe cell col=%d before = %.0f km/h%n",
                probeCol, probe.getRealValue());

        final Table3D t3 = map;
        SwingUtilities.invokeAndWait(() -> {
            try {
                ShiftCurveEditor ed = new ShiftCurveEditor(t3);
                ed.setSize(900, 570);
                ed.doLayout();
                BufferedImage img = new BufferedImage(900, 570, BufferedImage.TYPE_INT_ARGB);
                Graphics2D g = img.createGraphics();
                ed.paint(g);
                g.dispose();
                ImageIO.write(img, "png", out);
                System.out.println("wrote " + out.getAbsolutePath());
            } catch (Exception e) {
                e.printStackTrace();
            }
        });

        // Now prove the write path: set a value the way a drag does.
        probe.setRealValue("77");
        int addr = map.getStorageAddress();
        int idx = probe.getIndexInTable();
        int raw = ((rom[addr + idx * 2] & 0xFF) << 8) | (rom[addr + idx * 2 + 1] & 0xFF);
        System.out.printf("after setRealValue(77): cell = %.0f, ROM byte at 0x%06X = %d%n",
                probe.getRealValue(), addr + idx * 2, raw);
        System.out.println(raw == 77
                ? "EDIT REACHED THE ROM BYTES"
                : "EDIT DID NOT REACH THE ROM (raw=" + raw + ")");
        System.exit(0);
    }
}
