using System;
using System.Windows.Forms;

internal sealed partial class UsageToggleForm
{
    ToolStripMenuItem updateMenu;
    internal void SetUpdate(string text, bool enabled, Action clicked)
    {
        if(updateMenu==null) {
            updateMenu=new ToolStripMenuItem();
            updateMenu.Click+=delegate { if(updateAction!=null)updateAction(); };
            trayMenu.Items.Insert(trayMenu.Items.Count-2,updateMenu);
        }
        updateAction=clicked;
        updateMenu.Text=text ?? "";
        updateMenu.Available=text!=null;
        updateMenu.Enabled=enabled;
    }
    Action updateAction;
}
