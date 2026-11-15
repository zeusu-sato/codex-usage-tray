using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

public static partial class DualUiTest {
    static void RequireNumberPixels(Bitmap bitmap, int minimum, int brightness = 230) {
        int pixels = 0;
        // The symbol is only 18% opaque. Count bright foreground glyph pixels,
        // excluding the bottom gauge so it cannot hide missing number rendering.
        int bottom = bitmap.Height == 32 ? 26 : 12;
        for (int y = 0; y < bottom; y++) for (int x = 0; x < bitmap.Width; x++) {
            Color color = bitmap.GetPixel(x,y);
            if (color.A >= 220 && color.R >= brightness && color.G >= brightness && color.B >= brightness) pixels++;
        }
        Require(pixels >= minimum, "Missing foreground number/question mark in " + bitmap.Width + "px icon: " + pixels + " bright pixels");
    }
    static void SaveIcon(Icon icon, string stem, bool credit = false) {
        using (Bitmap actual = icon.ToBitmap()) {
            Require(actual.Width == 32 && actual.Height == 32, "Unexpected source icon size");
            actual.Save(stem + "-32.png");
            using (var small = new Bitmap(16,16))
            using (var graphics = Graphics.FromImage(small)) {
                graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                graphics.DrawImage(actual, new Rectangle(0,0,16,16));
                small.Save(stem + "-16.png");
                RequireNumberPixels(small, 2, credit ? 180 : 230);
            }
            RequireNumberPixels(actual, 8);
        }
    }
    public static void Capture(DualUiSession session, string folder, int index) {
        Invoke(session, delegate {
            Form host = session.Host;
            Require(Tabs(host).SelectedIndex == index, "Capture requested for hidden provider tab");
            using (var bitmap = new Bitmap(host.Width, host.Height)) {
                host.DrawToBitmap(bitmap, new Rectangle(0, 0, bitmap.Width, bitmap.Height));
                bitmap.Save(Path.Combine(folder, "provider-" + index + ".png"));
            }
            string provider = index == 0 ? "codex" : "claude";
            SaveIcon((Icon)Field(Views(host)[index], "usageIcon"), Path.Combine(folder, provider + "-icon"), Views(host)[index].Controls["UsageRemaining"].ForeColor.ToArgb() == Color.FromArgb(106,76,196).ToArgb());
            return null;
        });
    }
    public static void CapturePreviews(DualUiSession session, string folder) {
        Invoke(session, delegate {
            Type symbols = session.Host.GetType().Assembly.GetType("TraySymbols", true);
            MethodInfo create = symbols.GetMethod("Create", BindingFlags.Static | BindingFlags.NonPublic);
            foreach (string provider in new string[] { "codex", "claude" }) {
                foreach (double? value in new double?[] { 68, 24, 100, null }) {
                    string label = value.HasValue ? value.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : "unknown";
                    Color color = !value.HasValue ? Color.FromArgb(94,106,115)
                        : value == 24 ? Color.FromArgb(157,104,0) : Color.FromArgb(28,111,85);
                    using (Icon icon = (Icon)create.Invoke(null, new object[] { value, color, provider, null }))
                        SaveIcon(icon, Path.Combine(folder, provider + "-preview-" + label));
                }
            }
            return null;
        });
    }
    public static void CaptureCreditPreviews(DualUiSession session, string folder) {
        Directory.CreateDirectory(folder);
        Invoke(session, delegate {
            Type symbols = session.Host.GetType().Assembly.GetType("TraySymbols", true);
            MethodInfo create = symbols.GetMethod("Create", BindingFlags.Static | BindingFlags.NonPublic);
            string[] texts = { "812", "61k", ".9M", ".1M", "∞", "¤", "688", "1k" };
            string[] names = { "812", "61k", ".9M", ".1M", "infinity", "currency", "688", "1k" };
            for (int i = 0; i < texts.Length; i++) {
                using (Icon icon = (Icon)create.Invoke(null, new object[] { (double?)100, Color.FromArgb(106,76,196), "codex", texts[i] })) {
                    SaveIcon(icon, Path.Combine(folder, "credit-" + names[i]), true);
                    using (Bitmap bitmap = icon.ToBitmap()) {
                        for (int y = 0; y < 32; y++) for (int x = 0; x < 32; x++) {
                            Color c = bitmap.GetPixel(x,y);
                            if (c.R > 230 && c.G > 230 && c.B > 230)
                                Require(x >= 1 && x <= 30 && y >= 1 && y <= 25, "Credit glyph outside padded text area: " + texts[i]);
                        }
                        Require(bitmap.GetPixel(15,28).R < 200, "Credit gauge must contain only the track");
                    }
                }
            }
            return null;
        });
    }
    public static Task RefreshCredit(DualUiSession session, int index) {
        return (Task)Invoke(session, delegate {
            Form view = Views(session.Host)[index];
            return view.GetType().GetMethod("CheckUsageAsync", Fields).Invoke(view, null);
        });
    }
    public static void VerifyCredit(DualUiSession session, int index, string title, string summary) {
        Invoke(session, delegate {
            Form view = Views(session.Host)[index];
            Require(view.Controls["UsageRemaining"].Text == title, "Credit title missing");
            Require(view.Controls["UsageDetail"].Text.StartsWith(summary), "Credit summary missing");
            Require(((string)Field(view,"usageTooltip")).Contains(title), "Credit tooltip missing");
            Require(view.Controls["UsageForecast"].Text == "" && view.Controls["UsageChecked"].Top == view.Controls["UsageForecast"].Top, "Credit forecast row not hidden");
            using (Bitmap bitmap = ((Icon)Field(view,"usageIcon")).ToBitmap())
                Require(bitmap.GetPixel(0,0).ToArgb() == Color.FromArgb(106,76,196).ToArgb(), "Credit icon background mismatch");
            return null;
        });
    }
    public static void Stop(DualUiSession session) {
        if (!session.Finished.IsSet) {
            session.Host.Invoke(new Action(delegate {
                session.Host.GetType().GetField("exiting", Fields).SetValue(session.Host, true);
                session.Host.Close();
            }));
        }
        Require(session.Finished.Wait(10000), "UI loop did not finish during cleanup");
        Require(session.Thread.Join(1000), "UI thread survived cleanup");
        if (session.Failure != null) throw new InvalidOperationException("UI cleanup failed", session.Failure);
        Require(session.Host.IsDisposed, "Host was not disposed");
    }
}
