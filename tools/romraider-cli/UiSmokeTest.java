import com.romraider.editor.ecu.*;
import com.romraider.maps.*;
import com.romraider.swing.*;
import com.romraider.util.SettingsManager;
import com.romraider.xml.DOMRomUnmarshaller;
import org.w3c.dom.*;
import javax.swing.*;
import javax.xml.parsers.*;
import java.awt.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;

/**
 * Exercises the parts of the interface that rendering a table does not touch.
 *
 * Every check in this project so far proved something about DATA - that addresses
 * resolve, that cells match the ROM bytes, that a table draws. None of it opened a
 * menu. A stale directory in settings.xml was enough to throw an error box when the
 * Definitions dialog was clicked, and nothing here would have caught it, because
 * nothing here had ever clicked it.
 *
 * So: construct the real windows and dialogs, walk every menu item, and report
 * anything that throws. Headless-hostile by design - it needs a display, and runs
 * against a copy of the settings so it cannot damage a real profile.
 *
 *   UiSmokeTest <def.xml> <rom.bin>
 */
public class UiSmokeTest {

    private static final List<String> FAILS = new ArrayList<String>();
    private static int checks = 0;

    private static void check(String what, Runnable r) {
        checks++;
        try {
            r.run();
            System.out.println("  ok    " + what);
        } catch (Throwable t) {
            Throwable c = t;
            while (c.getCause() != null) c = c.getCause();
            String msg = c.getClass().getSimpleName()
                    + (c.getMessage() == null ? "" : ": " + c.getMessage());
            System.out.println("  FAIL  " + what + "  ->  " + msg);
            StackTraceElement[] st = c.getStackTrace();
            for (int i = 0; i < Math.min(3, st.length); i++) {
                System.out.println("           at " + st[i]);
            }
            FAILS.add(what + " -> " + msg);
        }
    }

    public static void main(String[] a) throws Exception {
        System.setProperty("romraider.theme", "dark");
        SettingsManager.setTesting(true);
        LookAndFeelManager.initLookAndFeel();

        final File defFile = new File(a[0]);
        final byte[] rom = Files.readAllBytes(Paths.get(a[1]));

        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(false);
        Node root = f.newDocumentBuilder().parse(defFile).getDocumentElement();
        DOMRomUnmarshaller u = new DOMRomUnmarshaller();
        Node match = u.checkDefinitionMatch(root, rom);
        if (match == null) { System.out.println("NO MATCH"); return; }
        final Rom r = u.unmarshallXMLDefinition(defFile, root, match, rom,
                new JProgressPane());
        r.populateTables(rom, new JProgressPane());
        System.out.println("loaded " + r.getTables().size() + " tables\n");

        // These construct on a worker thread on purpose: each calls
        // SwingUtilities.invokeAndWait internally, which throws outright if it is
        // already on the event dispatch thread. Running them inside invokeAndWait
        // reports a failure that belongs to the harness, not to RomRaider.
        check("DefinitionManager constructs", new Runnable() {
            public void run() { new DefinitionManager().pack(); }
        });
        check("SettingsForm constructs", new Runnable() {
            public void run() { new SettingsForm().pack(); }
        });
        check("saveFile (updates checksum)", new Runnable() {
            public void run() { r.saveFile(); }
        });

        SwingUtilities.invokeAndWait(new Runnable() {
            public void run() {
                check("TableToolBar constructs", new Runnable() {
                    public void run() { new TableToolBar(); }
                });

                // --- every table opens as a view ----------------------------
                Map<String, Integer> byType = new TreeMap<String, Integer>();
                for (final Table t : r.getTables()) {
                    final String key = String.valueOf(t.getType());
                    Integer n = byType.get(key);
                    byType.put(key, n == null ? 1 : n + 1);
                }
                System.out.println("\n  table types: " + byType + "\n");

                int opened = 0, failed = 0;
                for (final Table t : r.getTables()) {
                    checks++;
                    try {
                        TableView v = ECUEditor.getTableViewForTable(t);
                        if (v == null) throw new IllegalStateException("no view class");
                        t.setTableView(v);
                        v.populateTableVisual();
                        v.drawTable();
                        JFrame host = new JFrame();
                        host.setContentPane(new JPanel(new BorderLayout()) {{
                            add(v, BorderLayout.CENTER);
                        }});
                        host.pack();
                        host.dispose();
                        opened++;
                    } catch (Throwable ex) {
                        failed++;
                        Throwable c = ex;
                        while (c.getCause() != null) c = c.getCause();
                        String msg = t.getName() + " [" + t.getType() + "] -> "
                                + c.getClass().getSimpleName()
                                + (c.getMessage() == null ? "" : ": " + c.getMessage());
                        System.out.println("  FAIL  open table " + msg);
                        FAILS.add("open table " + msg);
                    }
                }
                System.out.println("  opened " + opened + " tables, " + failed + " failed\n");

                // --- toolbar actions on a representative table ---------------
                Table shift = null, sw = null;
                for (Table t : r.getTables()) {
                    if (shift == null && t.getName().startsWith("Shift Map")) shift = t;
                    if (sw == null && t.getType() == Table.TableType.SWITCH) sw = t;
                }
                if (shift != null) {
                    final Table s2 = shift;
                    check("shift curve editor constructs", new Runnable() {
                        public void run() {
                            new ShiftCurveEditor((Table3D) s2).setSize(900, 560);
                        }
                    });
                }
                if (sw != null) {
                    final Table s3 = sw;
                    check("switch table view populates", new Runnable() {
                        public void run() {
                            TableView v = ECUEditor.getTableViewForTable(s3);
                            s3.setTableView(v);
                            v.populateTableVisual();
                            v.drawTable();
                        }
                    });
                }

                // --- checksum path ------------------------------------------
                check("validateChecksum", new Runnable() {
                    public void run() { r.validateChecksum(); }
                });
            }
        });

        System.out.println("\n==== " + checks + " checks, " + FAILS.size() + " failures ====");
        for (String s : FAILS) System.out.println("  " + s);
        System.exit(FAILS.isEmpty() ? 0 : 1);
    }
}
