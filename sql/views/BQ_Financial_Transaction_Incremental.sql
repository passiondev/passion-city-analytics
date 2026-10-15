CREATE OR ALTER VIEW dbo.BQ_Financial_Transaction_Incremental AS
SELECT
    Id,
    BatchId,
    TransactionDateTime,
    TransactionCode,
    Summary,
    TransactionTypeValueId,
    SourceTypeValueId,
    CheckMicrEncrypted,
    ScheduledTransactionId,
    CAST(Guid AS NVARCHAR(36))                              AS Guid,
    CreatedDateTime,
    ModifiedDateTime,
    CreatedByPersonAliasId,
    ModifiedByPersonAliasId,
    ForeignKey,
    ProcessedByPersonAliasId,
    ProcessedDateTime,
    CheckMicrHash,
    AuthorizedPersonAliasId,
    FinancialGatewayId,
    FinancialPaymentDetailId,
    MICRStatus,
    CheckMicrParts,
    CAST(ForeignGuid AS NVARCHAR(36))                       AS ForeignGuid,
    ForeignId,
    Status,
    StatusMessage,
    IsSettled,
    SettledGroupId,
    SettledDate,
    IsReconciled,
    ShowAsAnonymous,
    FutureProcessingDateTime,
    NonCashAssetTypeValueId,
    SundayDate,
    TransactionDateKey,
    SettledDateKey,
    ForeignCurrencyCodeValueId,

    -- ingestion metadata for Make.com
    GETUTCDATE()                                            AS _loaded_at,
    'rock_rms'                                               AS _source_system

FROM dbo.FinancialTransaction
WHERE ModifiedDateTime >= (
        SELECT TOP(1) Last_Generated_Time
        FROM scheduler_log
        WHERE View_Name = 'BQ_Financial_Transaction_Incremental'
        ORDER BY Last_Generated_Time DESC
      )
  AND ModifiedDateTime <= CURRENT_TIMESTAMP