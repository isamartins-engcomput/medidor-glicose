import 'dart:async';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // Desenha o app por baixo da barra de status e da barra de navegação.
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);

  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent, // Torna o fundo transparente
    statusBarIconBrightness: Brightness.light, // Ícones brancos (use .dark se o fundo for claro)
  ));

  runApp(const GluCareApp());
}

const blue = Color(0xFF0950AE);
const purple = Color(0xFFA65AD7);
const navy = Color(0xFF080D3C);
const background = Color(0xFFF8F9FB);

class GluCareApp extends StatelessWidget {
  const GluCareApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'GluCare • Demonstração',
        theme: ThemeData(
          scaffoldBackgroundColor: background,
        ),
        home: const GluCareHome(),
      );
}

enum MealContext { fasting, twoHoursAfterMeal, recentlyAte }

extension MealContextLabel on MealContext {
  String get label => switch (this) {
    MealContext.fasting => 'Em jejum (8h ou mais)',
    MealContext.twoHoursAfterMeal => '2h após iniciar a refeição',
    MealContext.recentlyAte => 'Acabei de comer (menos de 2h)',
  };
}

class Reading {
  final DateTime recordedAt;
  final int value;
  final MealContext context;
  const Reading(this.recordedAt, this.value, this.context);

  String get category {
    if (value < 70) return 'Emergência • Hipoglicemia';
    if (context == MealContext.recentlyAte) {
      if (value < 140) return 'OK • faixa de referência';
      if (value < 200) return 'Sob atenção';
      if (value >= 200) return 'Emergência - Hiperglicemia';
    }
    if (context == MealContext.fasting) {
      if (value < 100) return 'OK • faixa de referência';
      if (value < 126) return 'Sob atenção';
      if (value >= 126) return 'Emergência - Hiperglicemia';
    }
    if (context == MealContext.twoHoursAfterMeal) {
      if (value < 140) return 'OK • faixa de referência';
      if (value < 199) return 'Sob atenção';
      if (value >= 200) return 'Emergência - Hiperglicemia';
    }
    return 'Sob atenção';
  }

  Color get color {
    if (value < 70) return const Color(0xFFD50000);
    if (context == MealContext.recentlyAte) {
      if (value < 140) return const Color(0xFF00B977);
      if (value < 199) return const Color(0xFFFFB43B);
      if (value >= 200) return const Color(0xFFD50000);
    }
    if (context == MealContext.fasting) {
      if (value < 100) return const Color(0xFF00B977);
      if (value <= 125) return const Color(0xFFFFB43B);
      return const Color(0xFFD50000);
    }
    if (context == MealContext.twoHoursAfterMeal) {
      if (value < 140) return const Color(0xFF00B977);
      if (value <= 199) return const Color(0xFFFFB43B);
      return const Color(0xFFD50000);
    }
    return const Color(0xFFFFB43B);
  }
}

class GluCareHome extends StatefulWidget {
  const GluCareHome({super.key});
  @override
  State<GluCareHome> createState() => _GluCareHomeState();
}

class _GluCareHomeState extends State<GluCareHome> {
  int tab = 1;
  bool measuring = false;
  bool running = false;
  int secondsLeft = 5;
  Timer? timer;
  MealContext? pendingContext;
  final random = Random();
  late final List<Reading> readings;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    readings = [
      Reading(now.subtract(const Duration(days: 1, hours: 9)), 185, MealContext.twoHoursAfterMeal),
      Reading(now.subtract(const Duration(days: 1, hours: 5)), 110, MealContext.fasting),
      Reading(now.subtract(const Duration(days: 1, hours: 2)), 95, MealContext.fasting),
      Reading(now.subtract(const Duration(minutes: 30)), 112, MealContext.fasting),
    ];
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  void switchTab(int next) {
    if (tab == next && !(next == 1 && measuring)) return;
    timer?.cancel();
    setState(() {
      tab = next;
      measuring = false;
      running = false;
      secondsLeft = 5;
      pendingContext = null;
    });
  }

  Future<void> openMeasurement() async {
    // Pergunta realizada antes de cada simulação.
    final contextChoice = await showDialog<MealContext>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Você acabou de comer?'),
        content: const Text(
          'Escolha o momento da medição simulada. As faixas de referência '
          'dependem do intervalo desde a refeição.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, MealContext.fasting),
            child: const Text('Estou em jejum (8h+)'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, MealContext.recentlyAte),
            child: const Text('Sim, há menos de 2h'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, MealContext.twoHoursAfterMeal),
            child: const Text('Comi há cerca de 2h'),
          ),
        ],
      ),
    );
    if (!mounted || contextChoice == null) return;
    timer?.cancel();
    setState(() {
      pendingContext = contextChoice;
      tab = 1;
      measuring = true;
      running = false;
      secondsLeft = 5;
    });
  }

  void startSimulation() {
    if (running) return;
    setState(() {
      running = true;
      secondsLeft = 5;
    });
    timer?.cancel();
    timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      if (secondsLeft > 1) {
        setState(() => secondsLeft--);
      } else {
        t.cancel();
        // Apenas uma simulação visual: NÃO representa leitura clínica.
        registerReading(random.nextInt(250)); // Sorteio uniforme de 0 a 249.
      }
    });
  }

  void registerReading(int value) {
    timer?.cancel();
    setState(() {
      readings.add(Reading(DateTime.now(), value, pendingContext ?? MealContext.fasting));
      measuring = false;
      running = false;
      secondsLeft = 5;
      tab = 1;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Medição fictícia adicionada: $value mg/dL')),
    );
  }

  String formatTime(DateTime date) =>
      '${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';

  String formatDay(DateTime date) {
    final today = DateUtils.dateOnly(DateTime.now());
    final day = DateUtils.dateOnly(date);
    if (day == today) return 'Hoje';
    if (day == today.subtract(const Duration(days: 1))) return 'Ontem';
    return '${date.day.toString().padLeft(2, '0')}/${date.month.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Column(children: [
          _header(), // fora do SafeArea: vai até o topo da tela
          Expanded(
            child: SafeArea(
              top: false, // topo já é tratado pelo header
              bottom: false,
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 360),
                reverseDuration: const Duration(milliseconds: 280),
                switchInCurve: Curves.easeOutCubic,
                switchOutCurve: Curves.easeInCubic,
                layoutBuilder: (current, previous) => Stack(
                  alignment: Alignment.center,
                  children: [...previous, if (current != null) current],
                ),
                transitionBuilder: (child, animation) {
                  final slide = Tween<Offset>(
                    begin: const Offset(0.07, 0),
                    end: Offset.zero,
                  ).animate(CurvedAnimation(parent: animation, curve: Curves.easeOutCubic));
                  return FadeTransition(
                    opacity: animation,
                    child: SlideTransition(position: slide, child: child),
                  );
                },
                child: KeyedSubtree(
                  key: ValueKey('$tab-$measuring'),
                  child: switch (tab) {
                    0 => _settings(),
                    2 => _history(),
                    _ => _home(),
                  },
                ),
              ),
            ),
          ),
          // Barra inferior respeita a área segura (gestos/botões do sistema)
          SafeArea(top: false, child: _bottomNav()),
        ]),
      );

  Widget _header() {
    final topInset = MediaQuery.of(context).padding.top; // altura da barra de status
    return Container(
      height: 60 + topInset,
      width: double.infinity,
      decoration: const BoxDecoration(
        gradient: LinearGradient(colors: [Color(0xFF12499F), purple]),
        borderRadius: BorderRadius.vertical(bottom: Radius.circular(10)),
      ),
      padding: EdgeInsets.fromLTRB(16, topInset, 16, 0),
      child: Row(children: [
        const Icon(Icons.water_drop_outlined, size: 34, color: Colors.white),
        const SizedBox(width: 7),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text('GluCare',
                style: TextStyle(fontFamily: 'serif', fontSize: 18, fontWeight: FontWeight.bold, color: Colors.white)),
            Row(children: const [
              CircleAvatar(radius: 5, backgroundColor: Color(0xFFA5D953)),
              SizedBox(width: 5),
              Text('Conectado • demo', style: TextStyle(fontSize: 11, color: Colors.white)),
            ]),
          ],
        ),
        const Spacer(),
        const Icon(Icons.science_outlined, size: 19, color: Colors.white70),
      ]),
    );
  }

  Widget _heading(String title, String subtitle) => Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontSize: 21, fontWeight: FontWeight.bold, color: navy)),
          Text(subtitle, style: const TextStyle(fontSize: 13, color: Color(0xFF0063A7))),
        ]),
      );

  Widget _home() => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _heading('Olá, usuário!', measuring ? 'Simulação de nova medição' : 'Seu nível de glicose no momento é:'),
        Expanded(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 280),
                child: measuring
                    ? Column(key: const ValueKey('measure'), mainAxisSize: MainAxisSize.min, children: [
                        _measurementCard(),
                        const SizedBox(height: 8),
                        Text(pendingContext?.label ?? '', style: const TextStyle(fontSize: 12, color: blue)),
                        const SizedBox(height: 18),
                        if (running) ...[
                          Text('$secondsLeft', style: const TextStyle(fontSize: 34, fontWeight: FontWeight.bold, color: blue)),
                          const Text('Simulando leitura...', style: TextStyle(color: blue)),
                          const SizedBox(height: 10),
                          const SizedBox(width: 150, child: LinearProgressIndicator()),
                        ] else ...[
                          _actionButton('Iniciar simulação (5 s)', startSimulation),
                        ],
                      ])
                    : _glucoseGauge(),
              ),
            ),
          ),
        ),
        if (!measuring)
          _newMeasurementButton()
        else
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: TextButton(onPressed: running ? null : () => switchTab(1), child: const Text('Voltar ao início')),
          ),
      ]);

  Widget _glucoseGauge() {
    final latest = readings.last;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Container(
        width: 232,
        height: 232,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: LinearGradient(
            colors: [latest.color.withValues(alpha: 0.65), latest.color],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        padding: const EdgeInsets.all(15),
        child: Container(
          decoration: const BoxDecoration(color: background, shape: BoxShape.circle),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            TweenAnimationBuilder<double>(
              key: ValueKey(latest.recordedAt.microsecondsSinceEpoch),
              tween: Tween(begin: 0, end: latest.value.toDouble()),
              duration: const Duration(milliseconds: 850),
              curve: Curves.easeOutCubic,
              builder: (context, value, _) => Text('${value.round()}',
                  style: const TextStyle(fontSize: 57, fontWeight: FontWeight.w800, height: 1, color: navy)),
            ),
            const Text('mg/dL (Simulado)', style: TextStyle(fontSize: 14, color: blue)),
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 5),
              decoration: BoxDecoration(color: latest.color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(20)),
              child: Text(latest.category,
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: latest.color)),
            ),
          ]),
        ),
      ),
      const SizedBox(height: 9),
      Text(latest.context.label, style: const TextStyle(fontSize: 12, color: blue)),
      const SizedBox(height: 7),
      Row(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.access_time, color: Colors.black87, size: 23),
        Text('${formatDay(latest.recordedAt)}, às ${formatTime(latest.recordedAt)}',
            style: const TextStyle(color: Color(0xFF00579C), fontSize: 16)),
      ]),
    ]);
  }

  Widget _measurementCard() => Container(
        width: 272,
        height: 236,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(18),
          gradient: const LinearGradient(
              colors: [Color(0xFF0752B3), Color(0xFF4B88DC)], begin: Alignment.topLeft, end: Alignment.bottomRight),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(children: [
          Positioned.fill(child: AnimatedWaves(active: running)),
          const Align(
            alignment: Alignment(0, -0.4),
            child: Text('Assopre no bocal\npor 5 segundos:',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 23, height: 1.25, color: Colors.white)),
          ),
          const Positioned(
              bottom: 14,
              left: 0,
              right: 0,
              child: Text('DEMONSTRAÇÃO',
                  textAlign: TextAlign.center, style: TextStyle(color: Colors.white70, fontSize: 10, letterSpacing: 2))),
        ]),
      );

  Widget _actionButton(String label, VoidCallback onPressed) => SizedBox(
        width: 260,
        height: 42,
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: const LinearGradient(colors: [blue, Color(0xFF6499E5)]),
            borderRadius: BorderRadius.circular(16),
          ),
          child: TextButton(onPressed: onPressed, child: Text(label, style: const TextStyle(color: Colors.white, fontSize: 15))),
        ),
      );

  Widget _newMeasurementButton() => Padding(
        padding: const EdgeInsets.fromLTRB(34, 0, 34, 22),
        child: SizedBox(
          width: double.infinity,
          height: 44,
          child: DecoratedBox(
            decoration: BoxDecoration(
                gradient: const LinearGradient(colors: [blue, Color(0xFF6499E5)]), borderRadius: BorderRadius.circular(17)),
            child: TextButton(
                onPressed: openMeasurement,
                child: const Text('Nova medição', style: TextStyle(fontSize: 21, fontFamily: 'serif', color: Colors.white))),
          ),
        ),
      );

  Widget _history() {
    final visible = readings.reversed.take(12).toList().reversed.toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _heading('Seu histórico', 'Acompanhe suas medições fictícias ao longo do tempo:'),
      const SizedBox(height: 20),
      Expanded(
        child: SingleChildScrollView(
          child: Column(children: [
            SizedBox(
              height: 285,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14),
                child: Row(children: [
                  SizedBox(
                      width: 28,
                      child: Column(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: const [
                            Text('700', style: TextStyle(fontSize: 9)),
                            Text('525', style: TextStyle(fontSize: 9)),
                            Text('350', style: TextStyle(fontSize: 9)),
                            Text('175', style: TextStyle(fontSize: 9)),
                            Text('0', style: TextStyle(fontSize: 9)),
                          ])),
                  const SizedBox(width: 8),
                  Expanded(child: LayoutBuilder(builder: (context, constraints) {
                    final barWidth = max(58.0, constraints.maxWidth / max(4, visible.length));
                    return SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      reverse: true,
                      child: SizedBox(
                        width: barWidth * visible.length,
                        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                          for (final r in visible)
                            SizedBox(
                                width: barWidth,
                                child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                                  Text('${r.value}',
                                      style: TextStyle(color: r.color, fontWeight: FontWeight.bold, fontSize: 12)),
                                  const SizedBox(height: 6),
                                  TweenAnimationBuilder<double>(
                                    key: ValueKey(r.recordedAt.microsecondsSinceEpoch),
                                    tween: Tween(begin: 0, end: r.value / 700 * 205),
                                    duration: const Duration(milliseconds: 650),
                                    curve: Curves.easeOutCubic,
                                    builder: (_, h, __) => Container(
                                      width: max(24, barWidth - 16),
                                      height: h,
                                      decoration: BoxDecoration(
                                          color: r.color, borderRadius: const BorderRadius.vertical(top: Radius.circular(4))),
                                    ),
                                  ),
                                  const SizedBox(height: 5),
                                  Text('${formatDay(r.recordedAt)}\n${formatTime(r.recordedAt)}',
                                      textAlign: TextAlign.center, style: const TextStyle(fontSize: 10)),
                                ])),
                        ]),
                      ),
                    );
                  })),
                ]),
              ),
            ),
            const SizedBox(height: 12),
            const Text('Valores demonstrativos • deslize o gráfico para ver mais',
                style: TextStyle(fontSize: 11, color: Colors.black54)),
            const SizedBox(height: 8),
            const Text('As cores consideram o contexto informado antes da simulação.',
                style: TextStyle(fontSize: 11, color: Colors.black54)),
          ]),
        ),
      ),
      _newMeasurementButton(),
    ]);
  }

  Widget _settings() => SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _heading('Configurações', 'Área técnica de personalização'),
          const SizedBox(height: 20),
          _settingsTile(Icons.person, 'Perfil', 'Seus dados e preferências', const Color(0xFF1700A8)),
          _settingsTile(Icons.settings, 'Editar configurações', 'Ajustar dispositivo e configurações', const Color(0xFF6311EE)),
          _settingsTile(Icons.warning_rounded, 'Emergências', 'Informações e contatos de emergência', const Color(0xFFD50000)),
          _settingsTile(Icons.insert_drive_file, 'Exportar dados', 'Baixe seus dados e histórico de medições', const Color(0xFF00C777)),
          const Padding(
            padding: EdgeInsets.all(20),
            child: Text('Modo de demonstração: não utilize estes dados para decisões de saúde.',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 11, color: Colors.black54)),
          ),
        ]),
      );

  Widget _settingsTile(IconData icon, String title, String subtitle, Color color) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
        child: Material(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          child: InkWell(
            borderRadius: BorderRadius.circular(16),
            onTap: () => ScaffoldMessenger.of(context)
                .showSnackBar(SnackBar(content: Text('$title: funcionalidade em desenvolvimento'))),
            child: Padding(
                padding: const EdgeInsets.all(14),
                child: Row(children: [
                  CircleAvatar(radius: 21, backgroundColor: color, child: Icon(icon, color: Colors.white, size: 27)),
                  const SizedBox(width: 10),
                  Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Color(0xFF333333))),
                    Text(subtitle, style: const TextStyle(fontSize: 10, color: Color(0xFF0063B0))),
                  ])),
                ])),
          ),
        ),
      );

  Widget _bottomNav() => Container(
        height: 65,
        decoration: const BoxDecoration(
          gradient: LinearGradient(colors: [Color(0xFF08499E), purple]),
          borderRadius: BorderRadius.vertical(top: Radius.circular(10)),
        ),
        child: Row(children: [
          _navItem(0, Icons.tune, 'Configurações'),
          _navItem(1, Icons.home_rounded, 'Início'),
          _navItem(2, Icons.history, 'Histórico'),
        ]),
      );

  Widget _navItem(int index, IconData icon, String label) => Expanded(
        child: InkWell(
          onTap: () => switchTab(index),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            AnimatedScale(
              scale: tab == index ? 1.08 : 0.9,
              duration: const Duration(milliseconds: 230),
              curve: Curves.easeOutBack,
              child: Icon(icon, size: 28, color: Colors.white),
            ),
            const SizedBox(height: 3),
            AnimatedDefaultTextStyle(
              duration: const Duration(milliseconds: 230),
              style: TextStyle(
                  fontSize: tab == index ? 12 : 10,
                  color: Colors.white,
                  fontWeight: tab == index ? FontWeight.w600 : FontWeight.normal),
              child: Text(label),
            ),
          ]),
        ),
      );
}

class AnimatedWaves extends StatefulWidget {
  final bool active;
  const AnimatedWaves({super.key, required this.active});

  @override
  State<AnimatedWaves> createState() => _AnimatedWavesState();
}

class _AnimatedWavesState extends State<AnimatedWaves> with SingleTickerProviderStateMixin {
  late final AnimationController controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1500),
  );

  @override
  void initState() {
    super.initState();
    if (widget.active) controller.repeat();
  }

  @override
  void didUpdateWidget(covariant AnimatedWaves oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !oldWidget.active) controller.repeat();
    if (!widget.active && oldWidget.active) controller.stop();
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: controller,
        builder: (_, __) => CustomPaint(
          painter: WavesPainter(phase: controller.value * 2 * pi),
          child: const SizedBox.expand(),
        ),
      );
}

class WavesPainter extends CustomPainter {
  final double phase;
  const WavesPainter({required this.phase});

  @override
  void paint(Canvas canvas, Size size) {
    const colors = [
      Color(0x5533B5F0),
      Color(0x7759D0F0),
      Color(0x9940DAE9),
    ];
    for (var i = 0; i < 3; i++) {
      final baseY = size.height * (0.61 + i * 0.10);
      final path = Path()..moveTo(0, baseY);
      for (var x = 0.0; x <= size.width + 3; x += 3) {
        final y = baseY + 13 * sin((x / size.width * 2 * pi) + phase * (i.isEven ? 1 : -1) + i);
        path.lineTo(x, y);
      }
      path
        ..lineTo(size.width, size.height)
        ..lineTo(0, size.height)
        ..close();
      canvas.drawPath(path, Paint()..color = colors[i]);
    }
  }

  @override
  bool shouldRepaint(covariant WavesPainter oldDelegate) => oldDelegate.phase != phase;
}