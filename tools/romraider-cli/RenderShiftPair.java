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
 * Renders an upshift/downshift pair through the curve editor, to a PNG.
 *
 * The point of the paired view is what it looks like, so compiling proves
 * nothing and asking someone else to describe it is not much better. This draws
 * it exactly as the application does, off screen, so the result can be looked at
 * directly.
 *
 *   RenderShiftPair <def.xml> <rom.bin> <out.png> [table name] [onlyRow]
 */
public class RenderShiftPair {
    public static void main(String[] a) throws Exception {
        System.setProperty("romraider.theme", "dark");
        com.romraider.util.SettingsManager.setTesting(true);
        com.romraider.swing.LookAndFeelManager.initLookAndFeel();

        File defFile = new File(a[0]);
        byte[] rom = Files.readAllBytes(Paths.get(a[1]));
        File out = new File(a[2]);
        final String want = a.length > 3 ? a[3] : "Shift Schedule 1 - Upshift";
        final int onlyRow = a.length > 4 ? Integer.parseInt(a[4]) : -1;

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

        Table3D up = null, down = null;
        final String partnerName = want.contains("Upshift")
                ? want.replace("Upshift", "Downshift")
                : want.replace("Downshift", "Upshift");
        for (Table t : r.getTables()) {
            if (!(t instanceof Table3D)) continue;
            if (want.equals(t.getName())) up = (Table3D) t;
            if (partnerName.equals(t.getName())) down = (Table3D) t;
        }
        if (up == null) {
            System.out.println("no table named " + want);
            for (Table t : r.getTables()) {
                if (t.getName() != null && t.getName().contains("Shift Schedule")) {
                    System.out.println("  have: " + t.getName());
                }
            }
            return;
        }
        System.out.println("up   = " + up.getName());
        System.out.println("down = " + (down == null ? "NOT FOUND" : down.getName()));

        final Table3D fup = up, fdown = down;
        SwingUtilities.invokeAndWait(() -> {
            try {
                ShiftCurveEditor ed = new ShiftCurveEditor(fup, fdown);
                if (onlyRow >= 0) ed.setOnlyRow(onlyRow);
                ed.setSize(900, 570);
                ed.doLayout();
                BufferedImage img = new BufferedImage(900, 570,
                        BufferedImage.TYPE_INT_ARGB);
                Graphics2D g = img.createGraphics();
                ed.paint(g);
                g.dispose();
                ImageIO.write(img, "png", out);
                System.out.println("wrote " + out.getAbsolutePath());
            } catch (Exception e) {
                e.printStackTrace();
            }
        });
    }
}
