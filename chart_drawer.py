import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def generate_chart(df, analysis):
    try:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df.index, df['Close'], label='Price', color='#1f77b4', linewidth=1.5)
        
        bias = analysis.get('bias', 'Neutral')
        ax.set_title(f"Market Analysis - Bias: {bias}")
        
        # رسم مستويات الدخول والخسارة والأهداف بشرط صحة قيمها الرقمية
        entry = analysis.get('entry')
        sl = analysis.get('sl')
        tp = analysis.get('tp')
        
        if entry and isinstance(entry, (int, float)) and entry > 0:
            ax.axhline(entry, color='blue', linestyle='--', label=f"Entry: {entry}")
        if sl and isinstance(sl, (int, float)) and sl > 0:
            ax.axhline(sl, color='red', linestyle=':', label=f"SL: {sl}")
        if tp and isinstance(tp, (int, float)) and tp > 0:
            ax.axhline(tp, color='green', linestyle=':', label=f"TP: {tp}")
        
        ax.legend(loc='upper left')
        ax.grid(True, alpha=0.3)
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        print(f"Error generating chart: {e}")
        try:
            plt.close('all')
        except:
            pass
        return None

