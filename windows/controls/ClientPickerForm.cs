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

internal sealed class ClientOption
{
    public readonly string Id;
    public readonly string Label;
    public ClientOption(string id, string label) { Id = id; Label = label; }
    public override string ToString() { return Label; }
}

internal sealed class ClientPickerForm : Form
{
    private readonly ComboBox choices;
    private readonly Label failure;
    private readonly Button selectButton;
    private readonly Button cancelButton;
    private readonly Func<string, Task<bool>> save;
    private bool saving;

    public ClientPickerForm(List<ClientOption> clients, string selectedId, Func<string, Task<bool>> selection, string providerName = "Codex")
    {
        save = selection;
        Name = "CodexClientPicker";
        Text = providerName + "を選ぶ";
        AccessibleName = Text;
        Font = new Font("Yu Gothic UI", 10F);
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96, 96);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(500, 246);
        BackColor = Color.FromArgb(247, 249, 250);
        Label explanation = new Label();
        explanation.Text = clients.Count == 0
            ? "対応する" + providerName + "が見つかりません。VS CodeまたはInsidersに" + providerName + "拡張機能をインストールしてから、再度選んでください。"
            : "監視する" + providerName + "を選んでください。\n選択だけではAIは起動しません。";
        explanation.Location = new Point(24, 20);
        explanation.Size = new Size(452, 64);
        choices = new ComboBox();
        choices.Name = "CodexClientChoices";
        choices.AccessibleName = "監視する" + providerName;
        choices.DropDownStyle = ComboBoxStyle.DropDownList;
        choices.Location = new Point(24, 94);
        choices.Size = new Size(452, 30);
        choices.TabIndex = 0;
        foreach (ClientOption client in clients)
        {
            int index = choices.Items.Add(client);
            if (client.Id == selectedId) choices.SelectedIndex = index;
        }
        failure = new Label();
        failure.Name = "ClientSelectionFailure";
        failure.Location = new Point(24, 136);
        failure.MaximumSize = new Size(452, 0);
        failure.AutoSize = true;
        failure.ForeColor = Color.FromArgb(148, 47, 43);
        selectButton = new Button();
        selectButton.Name = "SelectCodexClient";
        selectButton.Text = "これを使う";
        selectButton.Location = new Point(196, 190);
        selectButton.Size = new Size(144, 34);
        selectButton.Enabled = choices.SelectedIndex >= 0;
        selectButton.TabIndex = 1;
        selectButton.Click += async delegate { await SaveAsync(); };
        cancelButton = new Button();
        cancelButton.Name = "CancelCodexClient";
        cancelButton.Text = "キャンセル";
        cancelButton.Location = new Point(352, 190);
        cancelButton.Size = new Size(124, 34);
        cancelButton.TabIndex = 2;
        cancelButton.Click += delegate { Close(); };
        choices.SelectedIndexChanged += delegate { selectButton.Enabled = !saving && choices.SelectedIndex >= 0; };
        AcceptButton = selectButton;
        CancelButton = cancelButton;
        Controls.AddRange(new Control[] { explanation, choices, failure, selectButton, cancelButton });
        FormClosing += delegate(object sender, FormClosingEventArgs args)
        {
            if (saving && args.CloseReason == CloseReason.UserClosing) args.Cancel = true;
        };
    }

    public void ShowFailure(string text)
    {
        failure.Text = text;
        float scale;
        using (Graphics graphics = CreateGraphics()) scale = graphics.DpiY / 96F;
        selectButton.Top = Math.Max((int)(190 * scale), failure.Bottom + (int)(16 * scale));
        cancelButton.Top = selectButton.Top;
        ClientSize = new Size((int)(500 * scale), cancelButton.Bottom + (int)(22 * scale));
    }

    private async Task SaveAsync()
    {
        if (saving || choices.SelectedIndex < 0) return;
        saving = true;
        choices.Enabled = false;
        selectButton.Enabled = false;
        cancelButton.Enabled = false;
        bool saved = false;
        try { saved = await save(((ClientOption)choices.SelectedItem).Id); }
        finally
        {
            saving = false;
            if (!IsDisposed)
            {
                choices.Enabled = true;
                selectButton.Enabled = choices.SelectedIndex >= 0;
                cancelButton.Enabled = true;
            }
        }
        if (saved && !IsDisposed) Close();
    }
}

