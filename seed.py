# -*- coding: utf-8 -*-
"""演示数据生成脚本。

用法:
    .venv/bin/python seed.py          # 首次初始化(库非空则跳过)
    .venv/bin/python seed.py --drop   # 清空重建
"""
import os
import random
import sys
from datetime import datetime, timedelta

if os.environ.get('APP_ENV') == 'production':
    print('拒绝在生产环境运行 seed.py:演示数据包含公开的弱口令账号。')
    sys.exit(1)

from app import app
from models import ErrorBook, Feedback, Question, User, ViewLog, db

random.seed(42)

# (subject, chapter, difficulty, source, tags, question_latex, solution_latex)
QUESTIONS = [
    # ============================== 线性代数 ==============================
    ('线性代数', '2019', '中等', '東京工業大学 計算数理 2019',
     ['固有值', '对角化'],
     r'''设矩阵 $A = \begin{pmatrix} 2 & 1 & 0 \\ 1 & 2 & 0 \\ 0 & 0 & 3 \end{pmatrix}$。

(1) 求 $A$ 的所有固有值(特征值)与对应的固有向量。

(2) 求正交矩阵 $P$,使得 $P^{T} A P$ 为对角矩阵。''',
     r'''(1) 特征多项式为
$$\det(A - \lambda I) = \bigl[(2-\lambda)^2 - 1\bigr](3-\lambda) = (1-\lambda)(3-\lambda)^2.$$
故固有值为 $\lambda_1 = 1$(单根)与 $\lambda_2 = 3$(二重根)。

$\lambda_1 = 1$:解 $(A - I)\boldsymbol{x} = \boldsymbol{0}$ 得 $\boldsymbol{v}_1 = (1, -1, 0)^{T}$。

$\lambda_2 = 3$:解 $(A - 3I)\boldsymbol{x} = \boldsymbol{0}$ 得 $\boldsymbol{v}_2 = (1, 1, 0)^{T}$,$\boldsymbol{v}_3 = (0, 0, 1)^{T}$。

(2) 单位化后取
$$P = \begin{pmatrix} \tfrac{1}{\sqrt{2}} & \tfrac{1}{\sqrt{2}} & 0 \\ -\tfrac{1}{\sqrt{2}} & \tfrac{1}{\sqrt{2}} & 0 \\ 0 & 0 & 1 \end{pmatrix}, \qquad P^{T} A P = \mathrm{diag}(1, 3, 3).$$'''),

    ('线性代数', '2021', '困难', '東京大学 数理工学 2021',
     ['二次型', '正定性'],
     r'''设二次型 $f(x_1, x_2, x_3) = x_1^2 + 2x_2^2 + 3x_3^2 + 2ax_1 x_2 + 2x_1 x_3$。

问 $a$ 取何值时,$f$ 为正定二次型?''',
     r'''二次型矩阵为
$$A = \begin{pmatrix} 1 & a & 1 \\ a & 2 & 0 \\ 1 & 0 & 3 \end{pmatrix}.$$
由顺序主子式判别法:
$$\Delta_1 = 1 > 0, \quad \Delta_2 = 2 - a^2 > 0, \quad \Delta_3 = \det A = 6 - 3a^2 - 2 = 4 - 3a^2 > 0.$$
由 $\Delta_2 > 0$ 得 $|a| < \sqrt{2}$;由 $\Delta_3 > 0$ 得 $|a| < \tfrac{2}{\sqrt{3}}$。

因 $\tfrac{2}{\sqrt{3}} < \sqrt{2}$,故当 $-\tfrac{2}{\sqrt{3}} < a < \tfrac{2}{\sqrt{3}}$ 时 $f$ 正定。'''),

    ('线性代数', '行列式与逆矩阵', '简单', '京都大学 情報学研究科 2018',
     ['行列式'],
     r'''计算 $n$ 阶行列式
$$D_n = \begin{vmatrix} 2 & 1 & \cdots & 1 \\ 1 & 2 & \cdots & 1 \\ \vdots & \vdots & \ddots & \vdots \\ 1 & 1 & \cdots & 2 \end{vmatrix}.$$''',
     r'''将各行加到第一行,第一行元素均为 $n+1$,提出公因子:
$$D_n = (n+1)\begin{vmatrix} 1 & 1 & \cdots & 1 \\ 1 & 2 & \cdots & 1 \\ \vdots & & \ddots & \vdots \\ 1 & 1 & \cdots & 2 \end{vmatrix}.$$
再将第一行的 $(-1)$ 倍加到其余各行,化为上三角行列式,对角线为 $1, 1, \ldots, 1$,故
$$D_n = n + 1.$$'''),

    ('线性代数', '线性空间与线性变换', '中等', '大阪大学 基礎工学研究科 2020',
     ['线性变换', '核与像'],
     r'''设线性变换 $T: \mathbb{R}^3 \to \mathbb{R}^3$ 由矩阵
$$A = \begin{pmatrix} 1 & 2 & 1 \\ 2 & 4 & 2 \\ 1 & 2 & 1 \end{pmatrix}$$
给出。求 $\mathrm{Ker}\,T$ 与 $\mathrm{Im}\,T$ 的一组基,并验证维数定理。''',
     r'''对 $A$ 作行变换得阶梯形,秩为 $1$。

$\mathrm{Im}\,T$ 由列向量张成,一组基为 $\{(1, 2, 1)^{T}\}$,$\dim \mathrm{Im}\,T = 1$。

$\mathrm{Ker}\,T$:解 $x_1 + 2x_2 + x_3 = 0$,基为 $\{(-2, 1, 0)^{T}, (-1, 0, 1)^{T}\}$,$\dim \mathrm{Ker}\,T = 2$。

维数定理:$\dim \mathrm{Ker}\,T + \dim \mathrm{Im}\,T = 2 + 1 = 3 = \dim \mathbb{R}^3$,成立。'''),

    ('线性代数', '2016', '中等', '東北大学 情報科学研究科 2016',
     ['固有值', '矩阵幂'],
     r'''设 $A = \begin{pmatrix} 3 & 1 \\ 2 & 2 \end{pmatrix}$,求 $A^n$。''',
     r'''特征方程 $\lambda^2 - 5\lambda + 4 = 0$,得 $\lambda_1 = 1, \lambda_2 = 4$。

对应固有向量:$\lambda_1 = 1$ 时 $\boldsymbol{v}_1 = (1, -2)^{T}$;$\lambda_2 = 4$ 时 $\boldsymbol{v}_2 = (1, 1)^{T}$。

取 $P = \begin{pmatrix} 1 & 1 \\ -2 & 1 \end{pmatrix}$,则 $A = P\,\mathrm{diag}(1, 4)\,P^{-1}$,$P^{-1} = \tfrac{1}{3}\begin{pmatrix} 1 & -1 \\ 2 & 1 \end{pmatrix}$,

$$A^n = P \begin{pmatrix} 1 & 0 \\ 0 & 4^n \end{pmatrix} P^{-1} = \frac{1}{3}\begin{pmatrix} 1 + 2 \cdot 4^n & 4^n - 1 \\ 2 \cdot 4^n - 2 & 2 + 4^n \end{pmatrix}.$$'''),

    ('线性代数', '向量空间', '简单', '名古屋大学 工学研究科 2017',
     ['线性无关'],
     r'''判断向量组 $\boldsymbol{a}_1 = (1, 2, 3)^{T}$,$\boldsymbol{a}_2 = (2, 3, 4)^{T}$,$\boldsymbol{a}_3 = (3, 4, 5)^{T}$ 是否线性无关。''',
     r'''计算行列式
$$\begin{vmatrix} 1 & 2 & 3 \\ 2 & 3 & 4 \\ 3 & 4 & 5 \end{vmatrix} = 0$$
(第三行减第二行与第二行减第一行均为 $(1,1,1)$)。行列式为零,故向量组线性相关。事实上 $\boldsymbol{a}_1 - 2\boldsymbol{a}_2 + \boldsymbol{a}_3 = \boldsymbol{0}$。'''),

    # ============================== 微积分 ==============================
    ('微积分', '1 変数関数の微分法', '简单', '東京工業大学 計算数理 2015',
     ['极限', '洛必达法则'],
     r'''求极限
$$\lim_{x \to 0} \frac{e^x - 1 - x - \dfrac{x^2}{2}}{x^3}.$$''',
     r'''由 $e^x$ 的 Taylor 展开
$$e^x = 1 + x + \frac{x^2}{2} + \frac{x^3}{6} + o(x^3),$$
分子为 $\dfrac{x^3}{6} + o(x^3)$,故极限为 $\dfrac{1}{6}$。'''),

    ('微积分', '重積分', '中等', '東京大学 数理工学 2019',
     ['重积分', '变量替换'],
     r'''计算二重积分
$$I = \iint_D e^{-(x^2 + y^2)}\, dx\, dy,$$
其中 $D = \{(x, y) \mid x^2 + y^2 \le R^2\}$。并由此求 $\displaystyle\int_{-\infty}^{\infty} e^{-x^2} dx$。''',
     r'''极坐标替换 $x = r\cos\theta,\ y = r\sin\theta$:
$$I = \int_0^{2\pi}\!\! d\theta \int_0^R e^{-r^2} r\, dr = 2\pi \cdot \frac{1 - e^{-R^2}}{2} = \pi\bigl(1 - e^{-R^2}\bigr).$$
令 $R \to \infty$ 得 $\iint_{\mathbb{R}^2} e^{-(x^2+y^2)} dx\, dy = \pi$。

又该积分等于 $\left(\int_{-\infty}^{\infty} e^{-x^2} dx\right)^2$,故
$$\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}.$$'''),

    ('微积分', '級数', '中等', '京都大学 情報学研究科 2020',
     ['级数', '收敛判别'],
     r'''判断级数 $\displaystyle\sum_{n=1}^{\infty} \frac{n!}{n^n}$ 的敛散性。''',
     r'''用比值判别法:
$$\frac{a_{n+1}}{a_n} = \frac{(n+1)!}{(n+1)^{n+1}} \cdot \frac{n^n}{n!} = \left(\frac{n}{n+1}\right)^n = \frac{1}{\left(1 + \frac{1}{n}\right)^n} \to \frac{1}{e} < 1.$$
故级数收敛。'''),

    ('微积分', '2013', '困难', '東京工業大学 数学専攻 2013',
     ['广义积分'],
     r'''计算广义积分
$$\int_0^{\infty} \frac{\ln x}{1 + x^2}\, dx.$$''',
     r'''拆分为 $\int_0^1 + \int_1^{\infty}$。对后者作替换 $x = \tfrac{1}{t}$:
$$\int_1^{\infty} \frac{\ln x}{1+x^2} dx = \int_0^1 \frac{-\ln t}{1 + t^2} dt = -\int_0^1 \frac{\ln t}{1+t^2} dt.$$
两部分相消,故原积分为 $0$。'''),

    ('微积分', 'Taylor 展開', '简单', '北海道大学 情報科学研究科 2018',
     ['泰勒展开'],
     r'''求 $f(x) = \ln(1 + x)$ 在 $x = 0$ 处的 Taylor 展开(至 $x^4$ 项),并给出收敛域。''',
     r'''$$\ln(1+x) = x - \frac{x^2}{2} + \frac{x^3}{3} - \frac{x^4}{4} + \cdots = \sum_{n=1}^{\infty} \frac{(-1)^{n-1}}{n} x^n.$$
收敛域为 $-1 < x \le 1$。'''),

    ('微积分', '偏微分', '中等', '大阪大学 情報科学研究科 2021',
     ['偏导数', '极值'],
     r'''求函数 $f(x, y) = x^3 - 3xy + y^3$ 的所有极值点,并判断其类型。''',
     r'''驻点:$f_x = 3x^2 - 3y = 0$,$f_y = -3x + 3y^2 = 0$,解得 $(0, 0)$ 与 $(1, 1)$。

Hesse 矩阵 $H = \begin{pmatrix} 6x & -3 \\ -3 & 6y \end{pmatrix}$。

在 $(0,0)$:$\det H = -9 < 0$,为鞍点。

在 $(1,1)$:$\det H = 36 - 9 = 27 > 0$ 且 $f_{xx} = 6 > 0$,为极小值点,$f(1,1) = -1$。'''),

    ('微积分', '2017', '中等', '東京工業大学 計算数理 2017',
     ['条件极值', 'Lagrange乘数法'],
     r'''用 Lagrange 乘数法求 $f(x, y) = xy$ 在约束 $x^2 + y^2 = 1$ 下的最大值与最小值。''',
     r'''令 $L = xy - \lambda(x^2 + y^2 - 1)$,则
$$y = 2\lambda x, \qquad x = 2\lambda y.$$
两式相乘得 $xy = 4\lambda^2 xy$。若 $xy \neq 0$ 则 $\lambda = \pm\tfrac{1}{2}$,得驻点 $\left(\pm\tfrac{1}{\sqrt2}, \pm\tfrac{1}{\sqrt2}\right)$。

最大值 $f = \tfrac{1}{2}$(同号),最小值 $f = -\tfrac{1}{2}$(异号)。'''),

    # ============================== 微分方程 ==============================
    ('微分方程', '1 階常微分方程式', '简单', '東京工業大学 計算数理 2016',
     ['一阶线性'],
     r'''求解初值问题
$$\frac{dy}{dx} + 2y = e^{-x}, \qquad y(0) = 1.$$''',
     r'''积分因子 $\mu = e^{2x}$:
$$\frac{d}{dx}\left(e^{2x} y\right) = e^{x} \implies e^{2x} y = e^{x} + C.$$
代入 $y(0) = 1$:$1 = 1 + C$,得 $C = 0$。故
$$y = e^{-x}.$$'''),

    ('微分方程', '2 階線形微分方程式', '中等', '東京大学 情報理工学系研究科 2018',
     ['二阶常系数', '非齐次'],
     r'''求微分方程
$$y'' - 3y' + 2y = e^{x}$$
的通解。''',
     r'''特征方程 $\lambda^2 - 3\lambda + 2 = 0$,根为 $\lambda = 1, 2$,齐次通解 $y_h = C_1 e^{x} + C_2 e^{2x}$。

因 $e^x$ 与齐次解重复(单根共振),设特解 $y_p = A x e^{x}$,代入得
$$A(x + 2)e^x - 3A(x+1)e^x + 2Axe^x = -Ae^x = e^x \implies A = -1.$$

通解:$y = C_1 e^{x} + C_2 e^{2x} - x e^{x}$。'''),

    ('微分方程', '2020', '困难', '京都大学 情報学研究科 2020',
     ['方程组', '固有值法'],
     r'''求解微分方程组
$$\frac{d}{dt}\begin{pmatrix} x \\ y \end{pmatrix} = \begin{pmatrix} 1 & 1 \\ 4 & 1 \end{pmatrix} \begin{pmatrix} x \\ y \end{pmatrix}.$$''',
     r'''系数矩阵特征方程 $(1-\lambda)^2 - 4 = 0$,得 $\lambda = 3, -1$。

$\lambda = 3$:固有向量 $(1, 2)^{T}$;$\lambda = -1$:固有向量 $(1, -2)^{T}$。

通解:
$$\begin{pmatrix} x \\ y \end{pmatrix} = C_1 e^{3t} \begin{pmatrix} 1 \\ 2 \end{pmatrix} + C_2 e^{-t} \begin{pmatrix} 1 \\ -2 \end{pmatrix}.$$'''),

    ('微分方程', '変数分離形', '简单', '九州大学 システム情報科学府 2019',
     ['变量分离'],
     r'''求解 $\dfrac{dy}{dx} = \dfrac{y^2}{x}$($x > 0$)。''',
     r'''分离变量:$\dfrac{dy}{y^2} = \dfrac{dx}{x}$,积分得
$$-\frac{1}{y} = \ln x + C,$$
即 $y = -\dfrac{1}{\ln x + C}$(另有平凡解 $y \equiv 0$)。'''),

    ('微分方程', '2015', '中等', '東京工業大学 計算数理 2015',
     ['Laplace变换'],
     r'''用 Laplace 变换求解初值问题
$$y'' + 4y = \sin t, \qquad y(0) = 0,\ y'(0) = 0.$$''',
     r'''记 $Y(s) = \mathcal{L}[y]$。变换得
$$s^2 Y + 4Y = \frac{1}{s^2 + 1} \implies Y = \frac{1}{(s^2+1)(s^2+4)} = \frac{1}{3}\left(\frac{1}{s^2+1} - \frac{1}{s^2+4}\right).$$
逆变换:
$$y(t) = \frac{1}{3}\sin t - \frac{1}{6}\sin 2t.$$'''),

    ('微分方程', '偏微分方程式', '困难', '東京大学 数理工学 2021',
     ['热方程', '分离变数法'],
     r'''用分离变数法求解一维热传导方程的初边值问题:
$$u_t = u_{xx}, \quad 0 < x < \pi,\ t > 0; \qquad u(0, t) = u(\pi, t) = 0, \quad u(x, 0) = \sin x + 3\sin 2x.$$''',
     r'''设 $u = X(x)T(t)$,得 $X'' + \lambda X = 0$,$T' + \lambda T = 0$。

边界条件给出 $\lambda_n = n^2$,$X_n = \sin nx$,$T_n = e^{-n^2 t}$。

一般解 $u = \sum b_n e^{-n^2 t} \sin nx$。由初值 $b_1 = 1$,$b_2 = 3$,其余为零:
$$u(x, t) = e^{-t}\sin x + 3e^{-4t}\sin 2x.$$'''),

    # ============================== 复变函数 ==============================
    ('复变函数', '留数定理', '中等', '東京工業大学 数学専攻 2018',
     ['留数', '实积分'],
     r'''用留数定理计算
$$\int_{-\infty}^{\infty} \frac{dx}{x^4 + 1}.$$''',
     r'''上半平面极点:$z_1 = e^{i\pi/4}$,$z_2 = e^{3i\pi/4}$。

$$\mathrm{Res}_{z=z_k} \frac{1}{z^4+1} = \frac{1}{4z_k^3} = -\frac{z_k}{4}.$$

由 $z_1 + z_2 = e^{i\pi/4} + e^{3i\pi/4} = i\sqrt{2}$,得
$$\int_{-\infty}^{\infty} \frac{dx}{x^4+1} = 2\pi i \left(-\frac{z_1 + z_2}{4}\right) = 2\pi i \cdot \left(-\frac{i\sqrt{2}}{4}\right) = \frac{\pi\sqrt{2}}{2} = \frac{\pi}{\sqrt{2}}.$$'''),

    ('复变函数', 'Laurent 展開', '中等', '東京大学 数理工学 2017',
     ['Laurent级数'],
     r'''求 $f(z) = \dfrac{1}{(z-1)(z-2)}$ 在圆环 $1 < |z| < 2$ 内的 Laurent 展开。''',
     r'''部分分式:$f(z) = \dfrac{1}{z-2} - \dfrac{1}{z-1}$。

在 $1 < |z| < 2$ 内:
$$\frac{1}{z-2} = -\frac{1}{2}\cdot\frac{1}{1 - z/2} = -\sum_{n=0}^{\infty} \frac{z^n}{2^{n+1}}, \qquad \frac{1}{z-1} = \frac{1}{z}\cdot\frac{1}{1 - 1/z} = \sum_{n=1}^{\infty} \frac{1}{z^n}.$$

$$f(z) = -\sum_{n=0}^{\infty} \frac{z^n}{2^{n+1}} - \sum_{n=1}^{\infty} \frac{1}{z^n}.$$'''),

    ('复变函数', '2019', '简单', '大阪大学 基礎工学研究科 2019',
     ['Cauchy积分公式'],
     r'''计算积分 $\displaystyle\oint_{|z|=2} \frac{e^z}{z - 1}\, dz$(逆时针方向)。''',
     r'''$z = 1$ 在 $|z| = 2$ 内部,由 Cauchy 积分公式:
$$\oint_{|z|=2} \frac{e^z}{z-1} dz = 2\pi i \, e^{1} = 2\pi i e.$$'''),

    ('复变函数', '正則関数', '简单', '名古屋大学 情報学研究科 2020',
     ['Cauchy-Riemann方程'],
     r'''设 $f(z) = u(x, y) + iv(x, y)$,其中 $u = x^2 - y^2 + x$。求使 $f$ 为正则(全纯)函数的 $v$,并将 $f$ 表示为 $z$ 的函数。''',
     r'''由 Cauchy-Riemann 方程:$v_y = u_x = 2x + 1$,$v_x = -u_y = 2y$。

由第一式 $v = 2xy + y + \varphi(x)$,代入第二式得 $\varphi'(x) = 0$。

故 $v = 2xy + y + C$,且
$$f(z) = z^2 + z + iC.$$'''),

    ('复变函数', '2014', '困难', '東京工業大学 数学専攻 2014',
     ['留数', '三角积分'],
     r'''计算积分
$$\int_0^{2\pi} \frac{d\theta}{5 + 4\cos\theta}.$$''',
     r'''令 $z = e^{i\theta}$,则 $\cos\theta = \tfrac{1}{2}(z + z^{-1})$,$d\theta = \tfrac{dz}{iz}$:
$$I = \oint_{|z|=1} \frac{1}{5 + 2(z + z^{-1})} \frac{dz}{iz} = \frac{1}{i}\oint_{|z|=1} \frac{dz}{2z^2 + 5z + 2} = \frac{1}{i}\oint \frac{dz}{(2z+1)(z+2)}.$$
单位圆内极点为 $z = -\tfrac{1}{2}$(单极点),留数为
$$\mathrm{Res}_{z=-1/2} \frac{1}{(2z+1)(z+2)} = \frac{1}{2(z+2)}\bigg|_{z=-1/2} = \frac{1}{3}.$$

$$I = \frac{1}{i} \cdot 2\pi i \cdot \frac{1}{3} = \frac{2\pi}{3}.$$'''),

    # ============================== 概率统计 ==============================
    ('概率统计', '確率分布', '简单', '東京工業大学 計算数理 2018',
     ['期望', '方差'],
     r'''设随机变量 $X$ 服从参数为 $\lambda$ 的 Poisson 分布,即
$$P(X = k) = \frac{\lambda^k e^{-\lambda}}{k!}, \quad k = 0, 1, 2, \ldots$$
求 $E[X]$ 与 $V[X]$。''',
     r'''$$E[X] = \sum_{k=1}^{\infty} k \frac{\lambda^k e^{-\lambda}}{k!} = \lambda e^{-\lambda} \sum_{k=1}^{\infty} \frac{\lambda^{k-1}}{(k-1)!} = \lambda.$$

类似地 $E[X(X-1)] = \lambda^2$,故
$$V[X] = E[X^2] - (E[X])^2 = \lambda^2 + \lambda - \lambda^2 = \lambda.$$'''),

    ('概率统计', '最尤推定', '中等', '東京大学 情報理工学系研究科 2020',
     ['最大似然估计'],
     r'''设 $X_1, \ldots, X_n$ 独立同分布于正态分布 $N(\mu, \sigma^2)$。求 $\mu$ 与 $\sigma^2$ 的最大似然估计量,并讨论 $\hat{\sigma}^2$ 的无偏性。''',
     r'''对数似然
$$\ell(\mu, \sigma^2) = -\frac{n}{2}\ln(2\pi\sigma^2) - \frac{1}{2\sigma^2}\sum_{i=1}^n (X_i - \mu)^2.$$
求偏导并置零:
$$\hat{\mu} = \bar{X}, \qquad \hat{\sigma}^2 = \frac{1}{n}\sum_{i=1}^n (X_i - \bar{X})^2.$$
由于 $E[\hat{\sigma}^2] = \dfrac{n-1}{n}\sigma^2 \neq \sigma^2$,$\hat{\sigma}^2$ 是有偏估计(无偏修正为除以 $n - 1$)。'''),

    ('概率统计', '2021', '中等', '京都大学 情報学研究科 2021',
     ['条件概率', '贝叶斯'],
     r'''某检测方法对患病者呈阳性的概率为 $0.98$,对健康者呈阳性的概率为 $0.05$。人群患病率为 $0.1\%$。

某人检测呈阳性,求其确实患病的概率。''',
     r'''记患病为 $D$,阳性为 $+$。由 Bayes 公式:
$$P(D \mid +) = \frac{P(+ \mid D)P(D)}{P(+ \mid D)P(D) + P(+ \mid \bar{D})P(\bar{D})} = \frac{0.98 \times 0.001}{0.98 \times 0.001 + 0.05 \times 0.999} \approx 0.0192.$$
即约 $1.9\%$。'''),

    ('概率统计', '2017', '困难', '東京工業大学 数理・計算科学 2017',
     ['马尔可夫链'],
     r'''状态空间为 $\{1, 2, 3\}$ 的 Markov 链转移概率矩阵为
$$P = \begin{pmatrix} 0 & 1/2 & 1/2 \\ 1/2 & 0 & 1/2 \\ 1/2 & 1/2 & 0 \end{pmatrix}.$$
求平稳分布 $\boldsymbol{\pi}$,并判断该链是否收敛到平稳分布。''',
     r'''解 $\boldsymbol{\pi} P = \boldsymbol{\pi}$,$\sum_i \pi_i = 1$。由对称性 $\pi_1 = \pi_2 = \pi_3 = \tfrac{1}{3}$。

该链不可约、非周期(状态可经 2 步或 3 步回到自身,$\gcd(2,3)=1$)、有限状态,故为遍历链,对任意初始分布收敛到 $\boldsymbol{\pi} = \left(\tfrac{1}{3}, \tfrac{1}{3}, \tfrac{1}{3}\right)$。'''),

    ('概率统计', '大数の法則・中心極限定理', '中等', '大阪大学 情報科学研究科 2019',
     ['中心极限定理'],
     r'''掷一枚均匀硬币 $10000$ 次,用中心极限定理估计正面次数在 $4900$ 到 $5100$ 之间的概率(用标准正态分布函数 $\Phi$ 表示)。''',
     r'''正面次数 $S_n \sim B(10000, 0.5)$,$E[S_n] = 5000$,$\sqrt{V[S_n]} = 50$。

$$P(4900 \le S_n \le 5100) = P\left(-2 \le \frac{S_n - 5000}{50} \le 2\right) \approx \Phi(2) - \Phi(-2) = 2\Phi(2) - 1 \approx 0.9545.$$'''),

    ('概率统计', '確率変数の変換', '中等', '北海道大学 情報科学研究科 2020',
     ['变量变换', '密度函数'],
     r'''设 $X$ 服从 $[0, 1]$ 上的均匀分布,求 $Y = -\ln X$ 的概率密度函数。''',
     r'''对 $y > 0$:
$$F_Y(y) = P(-\ln X \le y) = P(X \ge e^{-y}) = 1 - e^{-y}.$$
求导得
$$f_Y(y) = e^{-y}, \quad y > 0,$$
即 $Y$ 服从参数为 $1$ 的指数分布。'''),

    # ============================== 向量解析 ==============================
    ('向量解析', 'ベクトル場の微分', '简单', '東京工業大学 計算数理 2014',
     ['梯度', '散度', '旋度'],
     r'''设标量场 $f = x^2 y z$,向量场 $\boldsymbol{A} = (xy, yz, zx)$。求:

(1) $\nabla f$;(2) $\nabla \cdot \boldsymbol{A}$;(3) $\nabla \times \boldsymbol{A}$。''',
     r'''(1) $\nabla f = (2xyz,\ x^2 z,\ x^2 y)$。

(2) $\nabla \cdot \boldsymbol{A} = y + z + x$。

(3)
$$\nabla \times \boldsymbol{A} = \begin{vmatrix} \boldsymbol{i} & \boldsymbol{j} & \boldsymbol{k} \\ \partial_x & \partial_y & \partial_z \\ xy & yz & zx \end{vmatrix} = (-y, -z, -x).$$'''),

    ('向量解析', 'Gauss の発散定理', '中等', '東京大学 数理工学 2016',
     ['高斯定理', '面积分'],
     r'''用 Gauss 散度定理计算通量
$$\iint_S \boldsymbol{A} \cdot \boldsymbol{n}\, dS, \qquad \boldsymbol{A} = (x^3, y^3, z^3),$$
其中 $S$ 为球面 $x^2 + y^2 + z^2 = a^2$,$\boldsymbol{n}$ 为外法向。''',
     r'''$\nabla \cdot \boldsymbol{A} = 3(x^2 + y^2 + z^2)$。由散度定理与球坐标:
$$\iint_S \boldsymbol{A} \cdot \boldsymbol{n}\, dS = \iiint_V 3r^2\, dV = 3\int_0^a r^2 \cdot 4\pi r^2\, dr = \frac{12\pi a^5}{5}.$$'''),

    ('向量解析', '2018', '中等', '京都大学 工学研究科 2018',
     ['Stokes定理', '线积分'],
     r'''用 Stokes 定理计算线积分
$$\oint_C \boldsymbol{A} \cdot d\boldsymbol{r}, \qquad \boldsymbol{A} = (-y, x, z^2),$$
其中 $C$ 为圆 $x^2 + y^2 = 1,\ z = 0$,取逆时针方向。''',
     r'''$\nabla \times \boldsymbol{A} = (0, 0, 2)$。取 $C$ 所围单位圆盘 $S$($\boldsymbol{n} = \boldsymbol{k}$):
$$\oint_C \boldsymbol{A} \cdot d\boldsymbol{r} = \iint_S (\nabla \times \boldsymbol{A}) \cdot \boldsymbol{k}\, dS = 2 \cdot \pi = 2\pi.$$'''),

    ('向量解析', '線積分', '简单', '東北大学 工学研究科 2019',
     ['线积分', '保守场'],
     r'''判断向量场 $\boldsymbol{F} = (2xy + z^2,\ x^2,\ 2xz)$ 是否为保守场;若是,求其势函数 $\varphi$。''',
     r'''验证 $\nabla \times \boldsymbol{F} = \boldsymbol{0}$:各分量偏导对称,确为保守场。

积分求势函数:
$$\varphi = \int (2xy + z^2)\, dx = x^2 y + x z^2 + g(y, z).$$
由 $\varphi_y = x^2$ 得 $g_y = 0$;由 $\varphi_z = 2xz$ 得 $g_z = 0$。

故 $\varphi = x^2 y + x z^2 + C$。'''),

    ('向量解析', '2012', '困难', '東京工業大学 計算数理 2012',
     ['曲面积分'],
     r'''求曲面积分 $\displaystyle\iint_S z\, dS$,其中 $S$ 为上半球面 $x^2 + y^2 + z^2 = a^2,\ z \ge 0$。''',
     r'''球坐标参数化:$z = a\cos\varphi$,$dS = a^2 \sin\varphi\, d\varphi\, d\theta$:
$$\iint_S z\, dS = \int_0^{2\pi}\!\! d\theta \int_0^{\pi/2} a\cos\varphi \cdot a^2 \sin\varphi\, d\varphi = 2\pi a^3 \cdot \frac{1}{2} = \pi a^3.$$'''),

    # ============================== 备注 ==============================
    ('备注', '出願情報', '简单', '内部整理',
     ['出願', '日程'],
     r'''\textbf{東京工業大学 情報理工学院 出願要点}

\begin{itemize}
\item 出願期間:例年 6 月上旬
\item 筆記試験:数学(微积分、线性代数为主)+ 専門科目
\item 口述試験:研究計画の説明
\end{itemize}''',
     r'''注意事项:提前联系指导教员,准备研究计划书。数学笔试范围以微积分、线性代数、概率统计为核心。'''),

    ('备注', '学習計画', '简单', '内部整理',
     ['计划'],
     r'''本季度复习计划:

1. 完成微积分过去问 2012--2021(每周 2 年份)

2. 线性代数错题本二刷

3. 概率统计:重点补强最尤推定与中心极限定理''',
     r'''进度记录:微积分已完成 2012--2016;线性代数错题本一刷完成。'''),
]

FEEDBACK_ITEMS = [
    ('公式渲染偶尔溢出卡片', '在卡片视图下,较长的行列式公式会超出卡片宽度,希望支持横向滚动。', '已处理', '已在卡片公式区加入横向滚动条。'),
    ('希望支持按年份区间筛选', '章节字段里的年份希望能按区间筛选,比如 2015-2020。', '待处理', ''),
    ('PDF 导出希望支持答案分离', '导出试卷时希望题目和答案分成两个部分,方便自测。', '待处理', ''),
    ('错题本希望支持导出 CSV', '想把错题列表导出成表格做统计。', '已处理', '可先使用 PDF 导出,CSV 导出已列入计划。'),
]


def seed(drop=False):
    with app.app_context():
        from sqlalchemy import inspect as _inspect
        if not drop and not _inspect(db.engine).has_table('questions'):
            print('数据库尚未初始化,请先执行: .venv/bin/flask --app app db upgrade')
            return
        if drop:
            db.drop_all()
            db.create_all()
        elif Question.query.first() is not None:
            print('数据库已有数据,跳过。如需重建请运行: seed.py --drop')
            return

        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        student = User(username='student', role='student')
        student.set_password('student123')
        db.session.add_all([admin, student])
        db.session.flush()

        base_date = datetime(2024, 1, 10, 9, 0, 0)
        questions = []
        for i, (subject, chapter, difficulty, source, tags, q, s) in enumerate(QUESTIONS):
            qu = Question(
                subject=subject, chapter=chapter, difficulty=difficulty, source=source,
                question_latex=q.strip(), solution_latex=s.strip(),
                created_at=base_date + timedelta(days=i * 17 % 500, hours=i % 11),
            )
            qu.tags_list = tags
            questions.append(qu)
        db.session.add_all(questions)
        db.session.flush()

        # 学生的错题本:抽约 1/3 的题
        picked = random.sample(questions, k=max(8, len(questions) // 3))
        notes_pool = ['计算粗心,符号搞错', '思路没想到,需要复习对应章节', '第二问不会做', '', '公式记错了', '']
        for i, qu in enumerate(picked):
            db.session.add(ErrorBook(
                user_id=student.id, question_id=qu.id,
                notes=random.choice(notes_pool),
                created_at=datetime.now() - timedelta(days=random.randint(0, 45)),
            ))

        for title, content, status, reply in FEEDBACK_ITEMS:
            db.session.add(Feedback(
                user_id=student.id, title=title, content=content, status=status, reply=reply,
                created_at=datetime.now() - timedelta(days=random.randint(1, 30)),
            ))

        # 查看日志:近 60 天随机行为
        for _ in range(400):
            db.session.add(ViewLog(
                user_id=random.choice([student.id, student.id, student.id, admin.id]),
                question_id=random.choice(questions).id,
                viewed_at=datetime.now() - timedelta(days=random.randint(0, 59),
                                                     minutes=random.randint(0, 1440)),
            ))

        db.session.commit()
        print(f'完成:{len(questions)} 道题,{len(picked)} 条错题,'
              f'{len(FEEDBACK_ITEMS)} 条反馈,400 条查看日志。')
        print('账号: admin/admin123 (管理员), student/student123 (学生)')


if __name__ == '__main__':
    seed(drop='--drop' in sys.argv)
