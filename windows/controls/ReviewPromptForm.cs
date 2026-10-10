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

internal sealed class ReviewPromptForm : Form
{
    public string Signature { get; private set; }
    private readonly Func<bool, Task<bool>> decide;
    private readonly Label description;
    private readonly Label failure;
    private readonly Button yesButton;
    private readonly Button noButton;
    private bool submitting;
    private bool completed;

    public ReviewPromptForm(string signature, string detail, Func<bool, Task<bool>> decision)
    {
        Signature = signature;
        decide = decision;
        Name = "AiReviewConfirmation";
        Text = "AIで対策を見直しますか";
        AccessibleName = Text;
        Font = new Font("Yu Gothic UI", 10F);
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96, 96);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(500, 248);
        BackColor = Color.FromArgb(247, 249, 250);

        Label heading = new Label();
        heading.Text = Text;
        heading.Font = new Font(Font.FontFamily, 13F, FontStyle.Bold);
        heading.Location = new Point(24, 20);
        heading.Size = new Size(452, 36);
        description = new Label();
        description.Name = "ReviewPromptDetail";
        description.Text = detail;
        description.AutoSize = true;
        description.MaximumSize = new Size(452, 0);
        description.Location = new Point(24, 64);
        failure = new Label();
        failure.Name = "ReviewPromptFailure";
        failure.AutoSize = true;
        failure.MaximumSize = new Size(452, 0);
        failure.Location = new Point(24, 140);
        failure.ForeColor = Color.FromArgb(148, 47, 43);

        yesButton = new Button();
        yesButton.Name = "ReviewYes";
        yesButton.Text = "はい";
        yesButton.AccessibleName = "はい、AIで見直しを開始する";
        yesButton.Size = new Size(112, 34);
        yesButton.Location = new Point(240, 190);
        yesButton.TabIndex = 1;
        yesButton.Click += async delegate { await SubmitAsync(true); };
        noButton = new Button();
        noButton.Name = "ReviewNo";
        noButton.Text = "いいえ";
        noButton.AccessibleName = "いいえ、AIを開始しない";
        noButton.Size = new Size(112, 34);
        noButton.Location = new Point(364, 190);
        noButton.TabIndex = 0;
        noButton.Click += async delegate { await SubmitAsync(false); };
        AcceptButton = noButton;
        CancelButton = noButton;
        noButton.DialogResult = DialogResult.None;
        Controls.AddRange(new Control[] { heading, description, failure, yesButton, noButton });
        Shown += delegate { Arrange(); noButton.Focus(); };
        FormClosing += async delegate(object sender, FormClosingEventArgs args)
        {
            if (!completed && args.CloseReason == CloseReason.UserClosing)
            {
                args.Cancel = true;
                await SubmitAsync(false);
            }
        };
    }

    public void ShowFailure(string text)
    {
        failure.Text = text;
        Arrange();
    }

    private void Arrange()
    {
        float scale;
        using (Graphics graphics = CreateGraphics()) scale = graphics.DpiY / 96F;
        failure.Top = description.Bottom + (int)(12 * scale);
        int top = Math.Max((int)(164 * scale), failure.Bottom + (int)(24 * scale));
        yesButton.Top = top;
        noButton.Top = top;
        ClientSize = new Size((int)(500 * scale), noButton.Bottom + (int)(24 * scale));
    }

    private async Task SubmitAsync(bool yes)
    {
        if (submitting || completed || IsDisposed) return;
        submitting = true;
        yesButton.Enabled = false;
        noButton.Enabled = false;
        try
        {
            if (await decide(yes))
            {
                if (IsDisposed) return;
                completed = true;
                Close();
            }
        }
        finally
        {
            submitting = false;
            if (!IsDisposed)
            {
                yesButton.Enabled = true;
                noButton.Enabled = true;
                noButton.Focus();
            }
        }
    }
}
