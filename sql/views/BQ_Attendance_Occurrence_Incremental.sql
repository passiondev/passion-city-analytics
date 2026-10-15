CREATE OR ALTER VIEW dbo.BQ_Attendance_Occurrence_Incremental AS
SELECT
    Id,
    GroupId,
    LocationId,
    ScheduleId,
    OccurrenceDate,
    DidNotOccur,
    CreatedDateTime,
    ModifiedDateTime,
    CreatedByPersonAliasId,
    ModifiedByPersonAliasId,
    CAST(Guid AS NVARCHAR(36))                              AS Guid,
    ForeignId,
    CAST(ForeignGuid AS NVARCHAR(36))                       AS ForeignGuid,
    ForeignKey,
    Notes,
    AnonymousAttendanceCount,
    StepTypeId,
    AcceptConfirmationMessage,
    DeclineConfirmationMessage,
    ShowDeclineReasons,
    DeclineReasonValueIds,
    SundayDate,
    Name,
    OccurrenceDateKey,
    AttendanceTypeValueId,
    AttendanceReminderLastSentDateTime,
    RootGroupTypeId,

    -- ingestion metadata for Make.com
    GETUTCDATE()                                            AS _loaded_at,
    'rock_rms'                                               AS _source_system

FROM dbo.AttendanceOccurrence
WHERE ModifiedDateTime >= (
        SELECT TOP(1) Last_Generated_Time
        FROM scheduler_log
        WHERE View_Name = 'BQ_Attendance_Occurrence_Incremental'
        ORDER BY Last_Generated_Time DESC
      )
  AND ModifiedDateTime <= CURRENT_TIMESTAMP