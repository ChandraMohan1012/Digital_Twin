class PatientProfile {
  final String id;
  final String fullName;
  final int age;
  final String gender;
  final double bmi;
  final String medicalNotes;
  final String deviceId;

  PatientProfile({
    required this.id,
    required this.fullName,
    required this.age,
    required this.gender,
    required this.bmi,
    required this.medicalNotes,
    required this.deviceId,
  });

  factory PatientProfile.fromJson(Map<String, dynamic> json) {
    return PatientProfile(
      id: json['id'] ?? '',
      fullName: json['full_name'] ?? 'Sample Patient',
      age: json['age'] ?? 38,
      gender: json['gender'] ?? 'unknown',
      bmi: (json['bmi'] is num) ? (json['bmi'] as num).toDouble() : 24.0,
      medicalNotes: json['medical_notes'] ?? '',
      deviceId: json['device_id'] ?? '',
    );
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is PatientProfile &&
          runtimeType == other.runtimeType &&
          id == other.id;

  @override
  int get hashCode => id.hashCode;
}

class TwinState {
  final String patientId;
  final String status;
  final String riskLabel;
  final double riskConfidence;
  final double latestHr;
  final double latestSpo2;
  final double latestTemp;
  final int latestBpSystolic;
  final int latestBpDiastolic;
  final double latestActivityLevel;
  final Map<String, double> rollingAvg24h;
  final String updatedAt;
  final Map<String, double> topRiskFactors;

  TwinState({
    required this.patientId,
    required this.status,
    required this.riskLabel,
    required this.riskConfidence,
    required this.latestHr,
    required this.latestSpo2,
    required this.latestTemp,
    required this.latestBpSystolic,
    required this.latestBpDiastolic,
    required this.latestActivityLevel,
    required this.rollingAvg24h,
    required this.updatedAt,
    required this.topRiskFactors,
  });

  factory TwinState.fromJson(Map<String, dynamic> json) {
    Map<String, double> parseMap(dynamic source) {
      if (source is Map) {
        return source.map((k, v) => MapEntry(k.toString(), (v as num).toDouble()));
      }
      return {};
    }

    return TwinState(
      patientId: json['patient_id'] ?? '',
      status: json['status'] ?? 'active',
      riskLabel: json['risk_label'] ?? 'low',
      riskConfidence: (json['risk_confidence'] is num) ? (json['risk_confidence'] as num).toDouble() : 0.15,
      latestHr: (json['latest_hr'] is num) ? (json['latest_hr'] as num).toDouble() : 76.0,
      latestSpo2: (json['latest_spo2'] is num) ? (json['latest_spo2'] as num).toDouble() : 98.0,
      latestTemp: (json['latest_temp'] is num) ? (json['latest_temp'] as num).toDouble() : 36.7,
      latestBpSystolic: (json['latest_bp_systolic'] is num) ? (json['latest_bp_systolic'] as num).toInt() : 118,
      latestBpDiastolic: (json['latest_bp_diastolic'] is num) ? (json['latest_bp_diastolic'] as num).toInt() : 76,
      latestActivityLevel: (json['latest_activity_level'] is num) ? (json['latest_activity_level'] as num).toDouble() : 5.0,
      rollingAvg24h: parseMap(json['rolling_avg_24h']),
      updatedAt: json['updated_at'] ?? DateTime.now().toIso8601String(),
      topRiskFactors: parseMap(json['top_risk_factors']),
    );
  }
}
