import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/patient_model.dart';

class ApiService {
  String host = "127.0.0.1";
  String activePort = "8000";
  String apiKey = "";

  void setHost(String newHost) {
    if (newHost.trim().isNotEmpty) {
      host = newHost.trim();
    }
  }

  String get baseHttpUrl => "http://$host:$activePort";
  String get baseWsUrl => "ws://$host:$activePort";

  Map<String, String> get _headers => {
    "Content-Type": "application/json",
    if (apiKey.isNotEmpty) "X-API-Key": apiKey,
  };

  WebSocketChannel? _wsChannel;
  StreamSubscription? _wsSubscription;

  final StreamController<TwinState> _twinStateController = StreamController<TwinState>.broadcast();
  final StreamController<Map<String, double>> _shapController = StreamController<Map<String, double>>.broadcast();
  final StreamController<bool> _onlineStatusController = StreamController<bool>.broadcast();

  Stream<TwinState> get twinStateStream => _twinStateController.stream;
  Stream<Map<String, double>> get shapStream => _shapController.stream;
  Stream<bool> get onlineStatusStream => _onlineStatusController.stream;

  // Check Backend Health with port and fallback IP check
  Future<bool> checkHealth() async {
    final hostsToTry = [host, "10.0.2.2", "127.0.0.1"];
    final portsToTry = ["8000", "8080", "8001"];

    for (String h in hostsToTry.toSet()) {
      for (String p in portsToTry) {
        try {
          final response = await http
              .get(Uri.parse("http://$h:$p/health"))
              .timeout(const Duration(seconds: 2));
          if (response.statusCode == 200) {
            host = h;
            activePort = p;
            _onlineStatusController.add(true);
            return true;
          }
        } catch (_) {
          continue;
        }
      }
    }
    _onlineStatusController.add(false);
    return false;
  }

  // Fetch List of Patients
  Future<List<PatientProfile>> fetchPatients() async {
    try {
      final response = await http.get(Uri.parse("$baseHttpUrl/patients"), headers: _headers);
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final List list = data['patients'] ?? [];
        return list.map((json) => PatientProfile.fromJson(json)).toList();
      }
    } catch (e) {
      debugPrint("Error fetching patients: $e");
    }
    return [
      PatientProfile(
        id: "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2",
        fullName: "Sample Patient",
        age: 38,
        gender: "female",
        bmi: 27.4,
        medicalNotes: "Prototype patient",
        deviceId: "device-001",
      )
    ];
  }

  // Register New Patient
  Future<PatientProfile?> registerPatient({
    required String fullName,
    required int age,
    required String gender,
    required double bmi,
    required String medicalNotes,
  }) async {
    try {
      final response = await http.post(
        Uri.parse("$baseHttpUrl/patients"),
        headers: _headers,
        body: jsonEncode({
          "full_name": fullName,
          "age": age,
          "gender": gender,
          "bmi": bmi,
          "medical_notes": medicalNotes,
        }),
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['patient'] != null) {
          return PatientProfile.fromJson(data['patient']);
        }
      }
    } catch (e) {
      debugPrint("Error registering patient: $e");
    }
    return null;
  }

  // Ingest Sensor Reading (6 features supported)
  Future<bool> ingestSensorData({
    required String patientId,
    required double hr,
    required double spo2,
    required double temp,
    required int bpSys,
    required int bpDia,
    double activityLevel = 5.0,
  }) async {
    try {
      final response = await http.post(
        Uri.parse("$baseHttpUrl/ingest"),
        headers: _headers,
        body: jsonEncode({
          "patient_id": patientId,
          "hr": hr,
          "spo2": spo2,
          "temp": temp,
          "bp_sys": bpSys,
          "bp_dia": bpDia,
          "activity_level": activityLevel,
        }),
      );
      return response.statusCode == 200;
    } catch (e) {
      debugPrint("Error ingesting sensor telemetry: $e");
      return false;
    }
  }

  // Initialize WebSocket Channel for Selected Patient
  void connectWebSocket(String patientId) {
    disconnectWebSocket();
    final wsUri = Uri.parse("$baseWsUrl/ws/twin/$patientId");
    debugPrint("[WebSocket] Connecting to Flutter channel: $wsUri");

    try {
      _wsChannel = WebSocketChannel.connect(wsUri);
      _onlineStatusController.add(true);

      _wsSubscription = _wsChannel!.stream.listen(
        (data) {
          try {
            final Map<String, dynamic> message = jsonDecode(data);
            if (message['event'] == 'initial_state' && message['data'] != null) {
              _twinStateController.add(TwinState.fromJson(message['data']));
            } else if (message['event'] == 'twin_update') {
              if (message['current_twin_state'] != null) {
                _twinStateController.add(TwinState.fromJson(message['current_twin_state']));
              }
              if (message['risk_prediction'] != null && message['risk_prediction']['top_risk_factors'] != null) {
                Map<String, double> shapMap = (message['risk_prediction']['top_risk_factors'] as Map)
                    .map((k, v) => MapEntry(k.toString(), (v as num).toDouble()));
                _shapController.add(shapMap);
              }
            }
          } catch (err) {
            debugPrint("[WebSocket] Flutter parse error: $err");
          }
        },
        onError: (err) {
          debugPrint("[WebSocket] Stream error: $err");
          _onlineStatusController.add(false);
        },
        onDone: () {
          debugPrint("[WebSocket] Connection closed");
          _onlineStatusController.add(false);
        },
      );
    } catch (err) {
      debugPrint("[WebSocket] Connect exception: $err");
      _onlineStatusController.add(false);
    }
  }

  void disconnectWebSocket() {
    _wsSubscription?.cancel();
    _wsChannel?.sink.close();
    _wsChannel = null;
  }

  void dispose() {
    disconnectWebSocket();
    _twinStateController.close();
    _shapController.close();
    _onlineStatusController.close();
  }
}
