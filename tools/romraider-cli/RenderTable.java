import com.romraider.maps.*;
import com.romraider.swing.*;
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
 * Renders a table exactly the way the editor does - same view class, same
 * populateTableVisual/drawTable calls, same look and feel - and writes it to a
 * PNG.
 *
 * The point is to be able to inspect what a user actually sees without asking
 * them to open the GUI and describe it. Reading values back through the API
 * proves the numbers are right; it does not prove the table is presented in a
 * form anyone would recognise. This does.
 *
 *   RenderTable <def.xml> <rom.bin> <table name substring> <out.png>
 */
public class RenderTable {
    public static void main(String[] a) throws Exception {
        System.setProperty("romraider.theme", "dark");
        com.romraider.util.SettingsManager.setTesting(true);
        com.romraider.swing.LookAndFeelManager.initLookAndFeel();

        File defFile = new File(a[0]);
        byte[] rom = Files.readAllBytes(Paths.get(a[1]));
        String want = a[2];
        File out = new File(a[3]);

        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(false);
        Document doc = f.newDocumentBuilder().parse(defFile);
        Node root = doc.getDocumentElement();
        DOMRomUnmarshaller u = new DOMRomUnmarshaller();
        Node match = u.checkDefinitionMatch(root, rom);
        if (match == null) { System.out.println("NO MATCH"); return; }
        Rom r = u.unmarshallXMLDefinition(defFile, root, match, rom, new JProgressPane());
        r.populateTables(rom, new JProgressPane());

        Table target = null;
        for (Table t : r.getTables()) {
            if (t.getName().contains(want)) { target = t; break; }
        }
        if (target == null) {
            System.out.println("NO SUCH TABLE. available:");
            for (Table t : r.getTables()) System.out.println("  " + t.getType() + "  " + t.getName());
            return;
        }

        final Table t = target;
        System.out.println("table   : " + t.getName());
        System.out.println("type    : " + t.getType());
        System.out.println("category: " + t.getCategory());
        System.out.println("scale   : units=" + t.getCurrentScale().getUnit()
                + " expr=" + t.getCurrentScale().getExpression()
                + " fmt=" + t.getCurrentScale().getFormat());

        SwingUtilities.invokeAndWait(() -> {
            try {
                TableView v = com.romraider.editor.ecu.ECUEditor.getTableViewForTable(t);
                t.setTableView(v);
                v.populateTableVisual();
                v.drawTable();

                // A real TableFrame so the titlebar and borders match the editor.
                JFrame host = new JFrame();
                host.setUndecorated(true);
                JPanel wrap = new JPanel(new BorderLayout());
                wrap.add(v, BorderLayout.CENTER);
                host.setContentPane(wrap);
                host.pack();
                Dimension d = host.getSize();
                System.out.println("rendered: " + d.width + "x" + d.height);
                // Off-screen so nothing flashes on the desktop, but still realised
                // so Swing lays out and paints normally.
                host.setLocation(-4000, -4000);
                host.setVisible(true);
                host.toBack();

                BufferedImage img = new BufferedImage(Math.max(d.width, 40),
                        Math.max(d.height, 40), BufferedImage.TYPE_INT_ARGB);
                Graphics2D g = img.createGraphics();
                wrap.paint(g);
                g.dispose();
                ImageIO.write(img, "png", out);
                System.out.println("wrote   : " + out.getAbsolutePath());
                host.dispose();
            } catch (Exception e) {
                e.printStackTrace();
            }
        });
        System.exit(0);
    }
}
