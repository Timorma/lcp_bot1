import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def generate_chart(df, analysis):
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df.index, df['Close'], label='Price', color='#1f77b4', linewidth=1.5)
    
    ax.set_title(f"Market Analysis - Bias: {analysis.get('bias')}")
    ax.axhline(analysis.get('entry'), color='blue', linestyle='--', label=f"Entry: {analysis.get('entry')}")
    ax.axhline(analysis.get('sl'), color='red', linestyle=':', label=f"SL: {analysis.get('sl')}")
    ax.axhline(analysis.get('tp'), color='green', linestyle=':', label=f"TP: {analysis.get('tp')}")
    
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)
    return buf
