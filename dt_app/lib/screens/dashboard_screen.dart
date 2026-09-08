import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:fl_chart/fl_chart.dart';
import '../models/patient_model.dart';
import '../services/api_service.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final ApiService _apiService = ApiService();

  List<PatientProfile> _patients = [];
  PatientProfile? _selectedPatient;
  TwinState? _currentTwinState;
  Map<String, double> _topRiskFactors = {};
  bool _isOnline = false;

  final List<FlSpot> _hrDataPoints = [];
  int _chartTimeCounter = 0;

  // Simulator Form Controllers
  final TextEditingController _hrCtrl = TextEditingController(text: "76");
  final TextEditingController _spo2Ctrl = TextEditingController(text: "98.0");
  final TextEditingController _tempCtrl = TextEditingController(text: "36.7");
  final TextEditingController _bpSysCtrl = TextEditingController(text: "118");
  final TextEditingController _bpDiaCtrl = TextEditingController(text: "76");
  final TextEditingController _actCtrl = TextEditingController(text: "5.0");

  @override
  void initState() {
    super.initState();
    _initDashboard();
  }

  Future<void> _initDashboard() async {
    final isHealthy = await _apiService.checkHealth();
    setState(() => _isOnline = isHealthy);

    final fetchedPatients = await _apiService.fetchPatients();
    final uniqueList = <PatientProfile>[];
    final seenIds = <String>{};
    for (var p in fetchedPatients) {
      if (!seenIds.contains(p.id)) {
        seenIds.add(p.id);
        uniqueList.add(p);
      }
    }

    setState(() {
      _patients = uniqueList;
      if (_patients.isNotEmpty) {
        _selectedPatient = _patients.first;
      }
    });

    if (_selectedPatient != null) {
      _apiService.connectWebSocket(_selectedPatient!.id);
    }

    _apiService.onlineStatusStream.listen((online) {
      if (mounted) setState(() => _isOnline = online);
    });

    _apiService.twinStateStream.listen((twinState) {
      if (mounted) {
        setState(() {
          _currentTwinState = twinState;
          _chartTimeCounter++;
          _hrDataPoints.add(FlSpot(_chartTimeCounter.toDouble(), twinState.latestHr));
          if (_hrDataPoints.length > 20) {
            _hrDataPoints.removeAt(0);
          }
        });
      }
    });

    _apiService.shapStream.listen((shapData) {
      if (mounted) {
        setState(() => _topRiskFactors = shapData);
      }
    });
  }

  void _onPatientChanged(PatientProfile? newPatient) {
    if (newPatient == null || newPatient.id == _selectedPatient?.id) return;
    setState(() {
      _selectedPatient = newPatient;
      _currentTwinState = null;
      _hrDataPoints.clear();
      _chartTimeCounter = 0;
    });
    _apiService.connectWebSocket(newPatient.id);
  }

  @override
  void dispose() {
    _apiService.dispose();
    _hrCtrl.dispose();
    _spo2Ctrl.dispose();
    _tempCtrl.dispose();
    _bpSysCtrl.dispose();
    _bpDiaCtrl.dispose();
    _actCtrl.dispose();
    super.dispose();
  }

  void _openServerConfigDialog() {
    final TextEditingController hostCtrl = TextEditingController(text: _apiService.host);
    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          backgroundColor: const Color(0xFF0F172A),
          title: Text("⚙️ Backend Connection Settings", style: GoogleFonts.inter(color: Colors.white, fontSize: 16)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text("Enter backend server IP or hostname (e.g. 10.0.2.2 for Android Emulator, 192.168.x.x for physical device):",
                  style: GoogleFonts.inter(color: Colors.white54, fontSize: 11)),
              const SizedBox(height: 12),
              _buildTextField(hostCtrl, "Server Host / IP"),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text("Cancel", style: TextStyle(color: Colors.white38)),
            ),
            ElevatedButton(
              onPressed: () async {
                Navigator.pop(context);
                _apiService.setHost(hostCtrl.text);
                await _initDashboard();
              },
              child: const Text("Connect"),
            )
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final isHighRisk = _currentTwinState?.riskLabel.toLowerCase() == 'high';

    return Scaffold(
      backgroundColor: const Color(0xFF0B0F19),
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              "Healthcare Digital Twin",
              style: GoogleFonts.inter(fontWeight: FontWeight.bold, fontSize: 18, color: Colors.white),
            ),
            Text(
              "Real-time Physiological Monitoring & XGBoost SHAP",
              style: GoogleFonts.inter(fontSize: 11, color: const Color(0xFF94A3B8)),
            ),
          ],
        ),
        actions: [
          GestureDetector(
            onTap: _openServerConfigDialog,
            child: Container(
              margin: const EdgeInsets.only(right: 12),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.white.withAlpha(13),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: Colors.white.withAlpha(25)),
              ),
              child: Row(
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: _isOnline ? const Color(0xFF10B981) : const Color(0xFFF59E0B),
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    _isOnline ? "Online (${_apiService.host})" : "Offline",
                    style: GoogleFonts.inter(fontSize: 12, color: Colors.white70),
                  ),
                ],
              ),
            ),
          )
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildPatientSelectorBar(),
            const SizedBox(height: 16),
            if (isHighRisk) ...[
              _buildAlertBanner(),
              const SizedBox(height: 16),
            ],
            Row(
              children: [
                Expanded(child: _buildRiskCard(isHighRisk)),
                const SizedBox(width: 12),
                Expanded(child: _buildPatientProfileCard()),
              ],
            ),
            const SizedBox(height: 20),
            Text(
              "Live Vital Telemetry",
              style: GoogleFonts.inter(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
            ),
            const SizedBox(height: 12),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: 1.3,
              children: [
                _buildVitalCard(
                  icon: "❤️",
                  title: "Heart Rate",
                  value: _currentTwinState?.latestHr.toStringAsFixed(1) ?? '--',
                  unit: "bpm",
                  avg: "24h: ${_currentTwinState?.rollingAvg24h['hr']?.toStringAsFixed(1) ?? '--'}",
                  color: Colors.redAccent,
                ),
                _buildVitalCard(
                  icon: "💨",
                  title: "SpO2",
                  value: _currentTwinState?.latestSpo2.toStringAsFixed(1) ?? '--',
                  unit: "%",
                  avg: "24h: ${_currentTwinState?.rollingAvg24h['spo2']?.toStringAsFixed(1) ?? '--'}",
                  color: Colors.cyanAccent,
                ),
                _buildVitalCard(
                  icon: "🌡️",
                  title: "Temperature",
                  value: _currentTwinState?.latestTemp.toStringAsFixed(1) ?? '--',
                  unit: "°C",
                  avg: "24h: ${_currentTwinState?.rollingAvg24h['temp']?.toStringAsFixed(1) ?? '--'}",
                  color: Colors.orangeAccent,
                ),
                _buildVitalCard(
                  icon: "🩸",
                  title: "Blood Pressure",
                  value: "${_currentTwinState?.latestBpSystolic ?? '--'}/${_currentTwinState?.latestBpDiastolic ?? '--'}",
                  unit: "mmHg",
                  avg: "24h: Dynamic",
                  color: Colors.purpleAccent,
                ),
                _buildVitalCard(
                  icon: "🏃",
                  title: "Activity Level",
                  value: _currentTwinState?.latestActivityLevel.toStringAsFixed(1) ?? '5.0',
                  unit: "/10",
                  avg: "MPU6050",
                  color: Colors.greenAccent,
                ),
              ],
            ),
            const SizedBox(height: 20),
            _buildChartCard(),
            const SizedBox(height: 20),
            _buildShapCard(),
            const SizedBox(height: 30),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _openSimulatorBottomSheet,
        backgroundColor: const Color(0xFF3B82F6),
        icon: const Icon(Icons.tune, color: Colors.white),
        label: Text("Inject Vitals", style: GoogleFonts.inter(fontWeight: FontWeight.bold, color: Colors.white)),
      ),
    );
  }

  Widget _buildPatientSelectorBar() {
    final selectedId = _patients.any((p) => p.id == _selectedPatient?.id)
        ? _selectedPatient?.id
        : (_patients.isNotEmpty ? _patients.first.id : null);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white.withAlpha(10),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withAlpha(20)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              const Text("👨‍⚕️ ", style: TextStyle(fontSize: 16)),
              DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  dropdownColor: const Color(0xFF0F172A),
                  value: selectedId,
                  items: _patients.map((p) {
                    return DropdownMenuItem<String>(
                      value: p.id,
                      child: Text(
                        "${p.fullName} (${p.deviceId})",
                        style: GoogleFonts.inter(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600),
                      ),
                    );
                  }).toList(),
                  onChanged: (String? newId) {
                    if (newId != null) {
                      final match = _patients.firstWhere((p) => p.id == newId);
                      _onPatientChanged(match);
                    }
                  },
                ),
              ),
            ],
          ),
          IconButton(
            icon: const Icon(Icons.person_add_alt_1, color: Color(0xFF3B82F6), size: 20),
            onPressed: _openRegisterPatientDialog,
          )
        ],
      ),
    );
  }

  Widget _buildAlertBanner() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.red.withAlpha(38),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.red.withAlpha(128)),
      ),
      child: Row(
        children: [
          const Text("⚠️ ", style: TextStyle(fontSize: 18)),
          Expanded(
            child: Text(
              "URGENT: Patient risk escalated to HIGH! Physiological assessment required.",
              style: GoogleFonts.inter(color: const Color(0xFFFCA5A5), fontSize: 12, fontWeight: FontWeight.bold),
            ),
          )
        ],
      ),
    );
  }

  Widget _buildRiskCard(bool isHighRisk) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white.withAlpha(8),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white.withAlpha(20)),
      ),
      child: Column(
        children: [
          Text("Risk Assessment", style: GoogleFonts.inter(fontSize: 12, color: const Color(0xFF94A3B8))),
          const SizedBox(height: 8),
          Text(
            (_currentTwinState?.riskLabel ?? "LOW").toUpperCase(),
            style: GoogleFonts.inter(
              fontSize: 22,
              fontWeight: FontWeight.w900,
              color: isHighRisk ? const Color(0xFFEF4444) : const Color(0xFF10B981),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            "Conf: ${((_currentTwinState?.riskConfidence ?? 0.15) * 100).toStringAsFixed(0)}%",
            style: GoogleFonts.inter(fontSize: 11, color: Colors.white54),
          ),
        ],
      ),
    );
  }

  Widget _buildPatientProfileCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white.withAlpha(8),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white.withAlpha(20)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_selectedPatient?.fullName ?? "Sample Patient",
              style: GoogleFonts.inter(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.white)),
          const SizedBox(height: 4),
          Text("ID: ${_selectedPatient?.id.substring(0, 8)}...",
              style: GoogleFonts.inter(fontSize: 10, color: Colors.white38)),
          const SizedBox(height: 6),
          Text("Notes: ${_selectedPatient?.medicalNotes ?? 'Routine telemetry'}",
              style: GoogleFonts.inter(fontSize: 10, color: const Color(0xFF94A3B8)),
              maxLines: 2,
              overflow: TextOverflow.ellipsis),
        ],
      ),
    );
  }

  Widget _buildVitalCard({
    required String icon,
    required String title,
    required String value,
    required String unit,
    required String avg,
    required Color color,
  }) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white.withAlpha(8),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withAlpha(20)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(icon, style: const TextStyle(fontSize: 18)),
              Text(title, style: GoogleFonts.inter(fontSize: 11, color: const Color(0xFF94A3B8))),
            ],
          ),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(value, style: GoogleFonts.inter(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white)),
              const SizedBox(width: 4),
              Text(unit, style: GoogleFonts.inter(fontSize: 11, color: Colors.white38)),
            ],
          ),
          Text(avg, style: GoogleFonts.inter(fontSize: 10, color: Colors.white38)),
        ],
      ),
    );
  }

  Widget _buildChartCard() {
    return Container(
      height: 200,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white.withAlpha(8),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white.withAlpha(20)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text("Heart Rate Telemetry Stream (bpm)",
              style: GoogleFonts.inter(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.white70)),
          const SizedBox(height: 12),
          Expanded(
            child: LineChart(
              LineChartData(
                gridData: const FlGridData(show: false),
                titlesData: const FlTitlesData(show: false),
                borderData: FlBorderData(show: false),
                lineBarsData: [
                  LineChartBarData(
                    spots: _hrDataPoints.isEmpty ? [const FlSpot(0, 76)] : _hrDataPoints,
                    isCurved: true,
                    color: const Color(0xFF3B82F6),
                    barWidth: 3,
                    isStrokeCapRound: true,
                    dotData: const FlDotData(show: false),
                    belowBarData: BarAreaData(
                      show: true,
                      color: const Color(0xFF3B82F6).withAlpha(38),
                    ),
                  )
                ],
              ),
            ),
          )
        ],
      ),
    );
  }

  Widget _buildShapCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white.withAlpha(8),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white.withAlpha(20)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text("XGBoost SHAP Explainability Risk Factors",
              style: GoogleFonts.inter(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.white)),
          const SizedBox(height: 12),
          if (_topRiskFactors.isEmpty)
            Text("Monitoring active. SHAP contributions will appear here.",
                style: GoogleFonts.inter(fontSize: 11, color: Colors.white38))
          else
            Column(
              children: _topRiskFactors.entries.map((e) {
                final isPositive = e.value >= 0;
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(e.key.toUpperCase(),
                          style: GoogleFonts.inter(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.white70)),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: isPositive ? Colors.red.withAlpha(50) : Colors.green.withAlpha(50),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          "${isPositive ? '+' : ''}${e.value.toStringAsFixed(3)}",
                          style: GoogleFonts.inter(
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            color: isPositive ? const Color(0xFFFCA5A5) : const Color(0xFF6EE7B7),
                          ),
                        ),
                      )
                    ],
                  ),
                );
              }).toList(),
            )
        ],
      ),
    );
  }

  void _openSimulatorBottomSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0F172A),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (context) {
        return Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text("Inject Telemetry Simulation",
                  style: GoogleFonts.inter(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white)),
              const SizedBox(height: 12),
              Row(
                children: [
                  ElevatedButton(
                    onPressed: () {
                      _hrCtrl.text = "76";
                      _spo2Ctrl.text = "98.0";
                      _tempCtrl.text = "36.7";
                      _bpSysCtrl.text = "118";
                      _bpDiaCtrl.text = "76";
                      _actCtrl.text = "4.5";
                    },
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.white10),
                    child: const Text("Normal Preset"),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    onPressed: () {
                      _hrCtrl.text = "145";
                      _spo2Ctrl.text = "87.0";
                      _tempCtrl.text = "39.5";
                      _bpSysCtrl.text = "170";
                      _bpDiaCtrl.text = "105";
                      _actCtrl.text = "1.0";
                    },
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.red.withAlpha(50)),
                    child: const Text("High Risk Spike", style: TextStyle(color: Colors.redAccent)),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(child: _buildTextField(_hrCtrl, "Heart Rate")),
                  const SizedBox(width: 8),
                  Expanded(child: _buildTextField(_spo2Ctrl, "SpO2 (%)")),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(child: _buildTextField(_tempCtrl, "Temp (°C)")),
                  const SizedBox(width: 8),
                  Expanded(child: _buildTextField(_bpSysCtrl, "BP Systolic")),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(child: _buildTextField(_bpDiaCtrl, "BP Diastolic")),
                  const SizedBox(width: 8),
                  Expanded(child: _buildTextField(_actCtrl, "Activity Level (0-10)")),
                ],
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () async {
                    if (_selectedPatient == null) return;
                    Navigator.pop(context);
                    await _apiService.ingestSensorData(
                      patientId: _selectedPatient!.id,
                      hr: double.tryParse(_hrCtrl.text) ?? 76.0,
                      spo2: double.tryParse(_spo2Ctrl.text) ?? 98.0,
                      temp: double.tryParse(_tempCtrl.text) ?? 36.7,
                      bpSys: int.tryParse(_bpSysCtrl.text) ?? 118,
                      bpDia: int.tryParse(_bpDiaCtrl.text) ?? 76,
                      activityLevel: double.tryParse(_actCtrl.text) ?? 5.0,
                    );
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF3B82F6),
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                  child: Text("Transmit Telemetry Payload",
                      style: GoogleFonts.inter(fontWeight: FontWeight.bold, color: Colors.white)),
                ),
              )
            ],
          ),
        );
      },
    );
  }

  void _openRegisterPatientDialog() {
    final TextEditingController nameCtrl = TextEditingController();
    final TextEditingController ageCtrl = TextEditingController(text: "42");
    final TextEditingController notesCtrl = TextEditingController();

    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          backgroundColor: const Color(0xFF0F172A),
          title: Text("👨‍⚕️ Register New Patient", style: GoogleFonts.inter(color: Colors.white, fontSize: 16)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _buildTextField(nameCtrl, "Full Name"),
              const SizedBox(height: 8),
              _buildTextField(ageCtrl, "Age"),
              const SizedBox(height: 8),
              _buildTextField(notesCtrl, "Medical Notes"),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text("Cancel", style: TextStyle(color: Colors.white38)),
            ),
            ElevatedButton(
              onPressed: () async {
                Navigator.pop(context);
                final newPatient = await _apiService.registerPatient(
                  fullName: nameCtrl.text,
                  age: int.tryParse(ageCtrl.text) ?? 38,
                  gender: "unknown",
                  bmi: 25.0,
                  medicalNotes: notesCtrl.text,
                );
                if (newPatient != null) {
                  final list = await _apiService.fetchPatients();
                  setState(() {
                    _patients = list;
                    _selectedPatient = newPatient;
                  });
                  _apiService.connectWebSocket(newPatient.id);
                }
              },
              child: const Text("Register Profile"),
            )
          ],
        );
      },
    );
  }

  Widget _buildTextField(TextEditingController ctrl, String label) {
    return TextField(
      controller: ctrl,
      style: GoogleFonts.inter(color: Colors.white, fontSize: 13),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: GoogleFonts.inter(color: Colors.white54, fontSize: 12),
        filled: true,
        fillColor: Colors.white.withAlpha(13),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
      ),
    );
  }
}
