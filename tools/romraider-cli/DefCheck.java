import com.romraider.maps.*;
import com.romraider.xml.DOMRomUnmarshaller;
import org.w3c.dom.*;
import javax.xml.parsers.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/**
 * Headless verifier: loads a RomRaider definition and a ROM using RomRaider's
 * OWN parser, then reports what it actually produced.
 *
 * The point is that nothing here re-implements the schema. If RomRaider would
 * silently skip a table, mis-read its address, or fail to match the calibration
 * ID, that shows up here exactly as it would in the GUI.
 *
 *   java DefCheck <definition.xml> <rom.bin> [--tables]
 */
public class DefCheck {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: DefCheck <definition.xml> <rom.bin> [--tables]");
            System.exit(2);
        }
        System.setProperty("java.awt.headless", "false");
        boolean listTables = args.length > 2 && args[2].equals("--tables");

        File defFile = new File(args[0]);
        byte[] rom = Files.readAllBytes(Paths.get(args[1]));
        String romName = new File(args[1]).getName();

        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(false);
        Document doc = f.newDocumentBuilder().parse(defFile);
        Node root = doc.getDocumentElement();

        DOMRomUnmarshaller u = new DOMRomUnmarshaller();

        // 1. cal-ID auto-selection. checkDefinitionMatch scans the CHILDREN of the
        //    node it is given, so it takes the root <roms> element, not a <rom>.
        int romBlocks = 0;
        NodeList kids = root.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node n = kids.item(i);
            if (n.getNodeType() == Node.ELEMENT_NODE && n.getNodeName().equals("rom")) romBlocks++;
        }
        Node match = u.checkDefinitionMatch(root, rom);
        System.out.printf("%-42s %2d rom blocks  ", romName, romBlocks);
        if (match == null) {
            System.out.println("NO MATCH");
            System.exit(1);
        }

        // 2. full unmarshal through RomRaider's own code path
        Rom r;
        try {
            r = u.unmarshallXMLDefinition(defFile, root, match, rom, new com.romraider.swing.JProgressPane());
        } catch (Throwable t) {
            System.out.println("MATCH but unmarshal FAILED: " + t);
            t.printStackTrace(System.out);
            System.exit(1);
            return;
        }
        RomID id = r.getRomID();
        List<Table> tables = new ArrayList<>();
        for (Table t : r.getTables()) tables.add(t);

        List<String> faulty = r.getFaultyTables();
        System.out.printf("match=%-28s tables=%3d  faulty=%d%n",
                id.getXmlid(), tables.size(), faulty == null ? 0 : faulty.size());

        if (faulty != null && !faulty.isEmpty())
            for (String s : faulty) System.out.println("      FAULTY: " + s);

        if (listTables) {
            Map<String,Integer> byType = new TreeMap<>();
            for (Table t : tables) {
                String k = String.valueOf(t.getType());
                byType.merge(k, 1, Integer::sum);
            }
            System.out.println("      by type: " + byType);
            for (Table t : tables) {
                System.out.printf("      %-42s %-10s @0x%06X size=%d%n",
                        t.getName(), t.getType(), t.getStorageAddress(), t.getDataSize());
            }
        }
    }
}
