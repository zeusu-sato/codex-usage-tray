using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class ToggleSwitch : CheckBox
{
    public ToggleSwitch()
    {
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint
            | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw
            | ControlStyles.Opaque, true);
        Appearance = Appearance.Normal;
        AutoSize = false;
        BackColor = Color.FromArgb(247, 249, 250);
        AccessibleRole = AccessibleRole.CheckButton;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        // Clear the full control, including rounded corners, after moves/resizes.
        // Transparent CheckBox painting can replay stale sibling text from its parent.
        e.Graphics.Clear(Parent == null ? BackColor : Parent.BackColor);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        float scale = e.Graphics.DpiX / 96F;
        float padding = 4F * scale;
        float height = Math.Min(32F * scale, Height - 2F * padding);
        RectangleF track = new RectangleF(padding, (Height - height) / 2F, Width - 2F * padding, height);
        if (track.Width < height || height <= 4F) return;
        bool known = Text == "ON" || Text == "OFF";
        Color fill = !known ? Color.FromArgb(234, 238, 240)
            : !Enabled ? (Checked ? Color.FromArgb(159, 187, 176) : Color.FromArgb(218, 224, 228))
            : Checked ? Color.FromArgb(28, 111, 85) : Color.FromArgb(105, 117, 126);
        Color stateText = known && Enabled ? Color.White : Color.FromArgb(73, 85, 93);
        using (GraphicsPath shape = new GraphicsPath())
        {
            shape.AddArc(track.Left, track.Top, height, height, 90, 180);
            shape.AddArc(track.Right - height, track.Top, height, height, 270, 180);
            shape.CloseFigure();
            using (Brush background = new SolidBrush(fill)) e.Graphics.FillPath(background, shape);
            using (Pen outline = new Pen(!known || !Enabled ? Color.FromArgb(174, 185, 192) : fill, scale))
                e.Graphics.DrawPath(outline, shape);
        }
        if (known)
        {
            float inset = 3F * scale;
            float diameter = height - 2F * inset;
            float left = Checked ? track.Right - inset - diameter : track.Left + inset;
            RectangleF thumb = new RectangleF(left, track.Top + inset, diameter, diameter);
            using (Brush white = new SolidBrush(Enabled ? Color.White : Color.FromArgb(247, 249, 250)))
                e.Graphics.FillEllipse(white, thumb);
            RectangleF label = Checked
                ? RectangleF.FromLTRB(track.Left + inset, track.Top, thumb.Left - inset, track.Bottom)
                : RectangleF.FromLTRB(thumb.Right + inset, track.Top, track.Right - inset, track.Bottom);
            TextRenderer.DrawText(e.Graphics, Checked ? "ON" : "OFF", Font, Rectangle.Round(label), stateText,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
        }
        else
        {
            // A missing/unfinished backend result is visibly unknown, never a false OFF.
            TextRenderer.DrawText(e.Graphics, Text, Font, Rectangle.Round(track), stateText,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
        }
        if (Focused && ShowFocusCues)
            ControlPaint.DrawFocusRectangle(e.Graphics, new Rectangle(1, 1, Width - 2, Height - 2),
                SystemColors.Highlight, Parent == null ? SystemColors.Control : Parent.BackColor);
    }

    protected override void OnPaintBackground(PaintEventArgs e) { e.Graphics.Clear(Parent == null ? BackColor : Parent.BackColor); }
    protected override void OnCheckedChanged(EventArgs e) { base.OnCheckedChanged(e); Invalidate(); }
    protected override void OnTextChanged(EventArgs e) { base.OnTextChanged(e); Invalidate(); }
    protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Cursor = Enabled ? Cursors.Hand : Cursors.Default; Invalidate(); }
    protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
    protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
}

