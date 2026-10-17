// Mahidol Faculty institutional theme tokens for Ant Design.
// Mirrors dashboard-automation/themes/mahidol-faculty palette: navy + gold, flat.
export const mahidolTheme = {
  token: {
    colorPrimary: '#0B2B5E',     // navy
    colorInfo: '#263988',
    colorLink: '#0B2B5E',
    colorSuccess: '#0F8F83',
    colorError: '#C94A4A',
    colorWarning: '#C9922B',
    borderRadius: 10,
    fontFamily: "Prompt, 'Noto Sans Thai', Tahoma, sans-serif",
    colorBgLayout: '#eef1f6',
  },
  components: {
    Layout: {
      headerBg: '#0B2B5E',
      headerColor: '#ffffff',
      siderBg: '#ffffff',
    },
    Menu: {
      itemSelectedBg: '#edf2fb',
      itemSelectedColor: '#0B2B5E',
      itemBorderRadius: 10,
      itemHeight: 42,
    },
    Button: { colorPrimary: '#0B2B5E', borderRadius: 10 },
    Card: { borderRadiusLG: 16 },
    Segmented: { borderRadius: 10 },
  },
};

export const GOLD = '#FECD54';
